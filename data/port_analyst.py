"""
Port Analyst Module
====================
Uses Gemini AI to generate supply chain status summaries for each major port.
Cached with ``config.GEMINI_CACHE_TTL_SECONDS`` (default ~24h) to cap API usage.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime

import warnings
with warnings.catch_warnings():
    warnings.simplefilter("ignore", category=FutureWarning)
    import google.generativeai as genai
from dotenv import load_dotenv

from config import GEMINI_CACHE_TTL_SECONDS
from data.cache import get_cached, set_cached
from data.ports_data import MAJOR_PORTS

load_dotenv()
logger = logging.getLogger(__name__)

# Configure Gemini
api_key = os.environ.get("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

CACHE_TTL = GEMINI_CACHE_TTL_SECONDS
CACHE_KEY = "ai_port_summaries_v4"

GENERATION_CONFIG = {
    "temperature": 0.7,  # Higher for more varied, specific responses
    "top_p": 0.9,
    "response_mime_type": "application/json",
}

SYSTEM_PROMPT = """You are a senior supply chain intelligence analyst providing LIVE OPERATIONAL BRIEFINGS for major global shipping ports.

CRITICAL REQUIREMENTS:
1. EVERY port MUST have a UNIQUE summary - no duplicate responses allowed
2. Include SPECIFIC details like: vessel queue counts, container dwell times, gate move volumes, or berth utilizations
3. Mention REGIONAL factors: weather impacts, labor conditions, customs processing, or trade policy effects
4. Reference ACTUAL trade lanes and cargo types relevant to each port's specialty

For each port, provide a 2-3 sentence intelligence briefing covering:
- Current throughput vs normal capacity (use percentages or vessel counts)
- Active disruptions OR specific operational conditions
- Regional supply chain context (trade partners, dominant cargo types)

NEVER use generic phrases like "Normal operations reported" or "No significant delays."
Each port has unique characteristics - highlight them.

Examples of GOOD responses:
{
    "Rotterdam": "Throughput at 94% capacity with 23 vessels at anchor. Container terminals seeing 6-hour average berth wait times. European inland rail connections operating at peak efficiency.",
    "Shanghai": "Export volumes up 12% week-over-week ahead of Lunar New Year. Yangshan terminal experiencing 18-hour truck queues. Trans-Pacific rates holding steady at $2,100/FEU.",
    "Singapore": "Malacca Strait transits running smoothly with 847 vessels processed this week. Bunker fuel availability tight following refinery maintenance. PSA terminals at 89% utilization."
}

Return a JSON object with port names as exact keys matching the input list.
"""



def _coerce_port_payload(raw) -> dict:
    """Turn Gemini's JSON into ``{port_name: payload}``.

    The model is asked for an object, but it often returns a list of
    ``{"port": ..., "summary": ...}`` rows, a list of single-key objects,
    or a one-key wrapper like ``{"ports": {...}}``.
    """
    if isinstance(raw, dict):
        looks_like_ports = any(
            isinstance(value, dict) and ("summary" in value or "disruption_penalty" in value)
            for value in raw.values()
        ) or any(isinstance(value, str) for value in raw.values())
        if looks_like_ports:
            return raw
        for wrap_key in ("ports", "summaries", "data", "results"):
            inner = raw.get(wrap_key)
            if isinstance(inner, (dict, list)):
                return _coerce_port_payload(inner)
        return raw

    if isinstance(raw, list):
        out: dict = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("port") or item.get("port_name")
            if name:
                out[str(name)] = item
                continue
            if len(item) == 1:
                key, value = next(iter(item.items()))
                out[str(key)] = value
        return out

    return {}


def _normalize_summaries(raw, port_names: list[str]) -> dict[str, dict]:
    """Reconcile Gemini's response keys with our canonical port names.

    Handles four common failure modes:
      1. Gemini returns a *string* instead of ``{"summary": ..., "disruption_penalty": ...}``
      2. Gemini uses slightly different casing, accents, or whitespace in key names
      3. Gemini omits some ports entirely
      4. Gemini returns a JSON *list* instead of an object
    """
    raw = _coerce_port_payload(raw)
    if not isinstance(raw, dict):
        return {}

    # Build a lookup: lowered/stripped → canonical name
    canonical = {name.lower().strip(): name for name in port_names}

    normalized: dict[str, dict] = {}
    for key, value in raw.items():
        # Match the returned key to our canonical port name
        match = canonical.get(key.lower().strip())
        if not match:
            # Try removing accents / special chars (e.g. "Colón" → "colon")
            import unicodedata
            folded = unicodedata.normalize("NFKD", key).encode("ascii", "ignore").decode().lower().strip()
            match = canonical.get(folded)
        if not match:
            logger.debug("Gemini returned unknown port key %r — skipping", key)
            continue

        # Handle plain-string values (Gemini sometimes skips the dict wrapper)
        if isinstance(value, str):
            value = {"summary": value, "disruption_penalty": 0.0}
        elif not isinstance(value, dict):
            continue

        # Ensure required keys exist with correct types
        value.setdefault("summary", "")
        value.setdefault("disruption_penalty", 0.0)
        try:
            value["disruption_penalty"] = float(value["disruption_penalty"])
        except (TypeError, ValueError):
            value["disruption_penalty"] = 0.0

        normalized[match] = value

    missing = set(port_names) - set(normalized)
    if missing:
        logger.warning(
            "Gemini did not return summaries for %d/%d ports: %s",
            len(missing), len(port_names), ", ".join(sorted(missing)),
        )

    return normalized


def generate_port_summaries() -> dict[str, dict]:
    """Generate AI-powered summaries for all major ports.

    Returns
    -------
    dict[str, dict]
        Mapping of port name → {"summary": str, "disruption_penalty": float}
        Falls back to empty dict if API fails.
    """
    # Check cache first
    cached = get_cached(CACHE_KEY, ttl=CACHE_TTL)
    if cached:
        logger.info("Using cached port summaries (updated %s)", cached.get("_updated", "unknown"))
        summaries = cached.get("summaries", {})
        if not isinstance(summaries, dict):
            port_names = [name for name, _, _, _ in MAJOR_PORTS]
            summaries = _normalize_summaries(summaries, port_names)
        return summaries if isinstance(summaries, dict) else {}

    if not api_key:
        logger.warning("GEMINI_API_KEY not set. Using fallback summaries.")
        return {}

    # 1. Gather context: get top 100 recent news articles (grounding AI in reality)
    from data.rss_fetcher import fetch_rss_articles
    recent_news = fetch_rss_articles(max_items=100)

    news_context = "RECENT SUPPLY CHAIN NEWS:\n\n"
    for art in recent_news:
        news_context += f"- {art.get('title', '')}: {art.get('description', '')[:200]}\n"

    # 2. Build port list
    port_names = [name for name, _, _, _ in MAJOR_PORTS]

    logger.info("Generating AI summaries for %d ports based on live news...", len(port_names))

    today_str = datetime.now().strftime("%B %d, %Y")

    SYSTEM_PROMPT = f"""You are a senior supply chain intelligence analyst providing LIVE OPERATIONAL CONTEXT for major global shipping ports. Today's date is {today_str}.

You will be provided with a list of recent supply chain news headlines and snippets.
Using this news context AND your expert knowledge of current global events, evaluate the status of the requested ports.

CRITICAL REQUIREMENTS:
1. You MUST return an entry for ALL {len(port_names)} ports. Do NOT skip any.
2. EVERY port MUST have a UNIQUE evaluation - no duplicate responses allowed.
3. For each port, provide a 'summary' (1-2 very concise sentences) detailing exactly what is currently happening there (e.g., vessel queues, specific delays, strike impacts, trade lane volumes, or capacity utilization). Include specific metrics or percentages where possible.
4. For each port, provide a 'disruption_penalty' value from 0.0 to 50.0.
   - 0.0 means the port is operating normally or perfectly.
   - 10.0-20.0 means moderate delays or friction.
   - 30.0-40.0 means severe disruption (major strikes, heavy congestion).
   - 50.0 means catastrophic closure or complete blockade (e.g., trapped ships, war zone, complete port strike).
5. Use the EXACT port names provided as JSON keys. Do not rename or rephrase them.

Return a JSON object where the keys are the EXACT port names provided, and the values are objects containing the 'summary' and 'disruption_penalty'.

Example Output Format:
{{
    "Rotterdam": {{"summary": "Operating at 94% capacity with minor 6-hour berth wait times. Inland rail is clear.", "disruption_penalty": 5.0}},
    "Dubai": {{"summary": "Severe congestion as ships redirect due to Red Sea attacks. Yard saturation resulting in 4-day delays.", "disruption_penalty": 25.5}}
}}
"""

    try:
        model = genai.GenerativeModel(
            model_name="gemini-3-flash-preview",
            generation_config=GENERATION_CONFIG,
            system_instruction=SYSTEM_PROMPT
        )

        prompt = f"""{news_context}

Analyze the current supply chain status for these {len(port_names)} major shipping ports:

{chr(10).join(f"- {name}" for name in port_names)}

You MUST return a JSON entry for EVERY port listed above ({len(port_names)} total).
Provide the JSON status summary and disruption_penalty for each port."""

        response = model.generate_content(prompt)
        raw_summaries = json.loads(response.text)
        summaries = _normalize_summaries(raw_summaries, port_names)

        # Cache the result
        set_cached(CACHE_KEY, {
            "summaries": summaries,
            "_updated": datetime.now().strftime("%Y-%m-%d %H:%M")
        })

        logger.info(
            "Generated and cached %d/%d port summaries",
            len(summaries), len(port_names),
        )
        return summaries

    except Exception as e:
        logger.error("Gemini dynamic port analysis failed: %s", e)
        return {}


# ---------------------------------------------------------------------------
# Aggregate disruption signal (feeds the geopolitical category composite)
# ---------------------------------------------------------------------------

def get_aggregate_disruption_score() -> tuple[float, int, str]:
    """Roll up all per-port AI disruption_penalty values into one 0-100
    health score so the geopolitical category can blend in a port-grounded
    signal on top of the raw news-severity score.

    Uses the mean disruption_penalty (0-50 scale, 0=normal, 50=catastrophic)
    across every port with a summary, converted via ``score = 100 - 2 * avg``
    so a fleet-wide average penalty of 25 (moderate-to-severe) reads as 50
    (Stressed), and an average of 0 reads as a perfect 100.

    Returns
    -------
    tuple[float, int, str]
        (score_0_100, port_count_with_data, summary_str). Raises if no port
        summaries are available (e.g. GEMINI_API_KEY unset) — the caller
        decides how to fall back (blend skipped, geopolitical score used
        as-is).
    """
    summaries = generate_port_summaries()
    if not summaries:
        raise ValueError("No port summaries available (Gemini unset or fetch failed)")

    penalties = []
    for data in summaries.values():
        if isinstance(data, dict) and "disruption_penalty" in data:
            try:
                penalties.append(float(data["disruption_penalty"]))
            except (TypeError, ValueError):
                continue

    if not penalties:
        raise ValueError("Port summaries present but no valid disruption_penalty values")

    avg_penalty = sum(penalties) / len(penalties)
    score = round(max(0.0, min(100.0, 100.0 - 2.0 * avg_penalty)), 1)
    worst_count = sum(1 for p in penalties if p >= 25.0)
    summary = (
        f"{len(penalties)} ports scanned, avg disruption penalty {avg_penalty:.1f}/50, "
        f"{worst_count} at severe-or-worse levels"
    )
    return score, len(penalties), summary
