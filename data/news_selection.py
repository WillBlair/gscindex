"""Freshness and diversity helpers for news article selection."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_TRACKING_PREFIXES = ("utm_",)
_TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
_TITLE_TOKEN_RE = re.compile(r"[^a-z0-9]+")
_LOW_SIGNAL_PHRASES = {
    "no tropical cyclones at this time",
    "there are no tropical cyclones at this time",
    "there are no active tropical cyclones",
    "tropical cyclone formation is not expected during the next",
}


def canonicalize_url(url: str) -> str:
    """Normalize URLs so tracking params do not defeat dedupe."""
    if not url:
        return ""

    parts = urlsplit(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in _TRACKING_PARAMS and not key.startswith(_TRACKING_PREFIXES)
    ]
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query), ""))


def _normalized_title(title: str) -> str:
    tokens = [token for token in _TITLE_TOKEN_RE.split(title.lower()) if token]
    return " ".join(tokens[:14])


def article_fingerprint(article: dict) -> str:
    """Return a stable identifier for an article."""
    canonical_url = canonicalize_url(str(article.get("url", "")))
    basis = canonical_url or _normalized_title(str(article.get("title", "")))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def is_low_signal_article(article: dict) -> bool:
    """Return True for public-feed housekeeping items that add no risk signal."""
    title = str(article.get("title", "")).strip().lower()
    description = str(article.get("description", "")).strip().lower()
    text = f"{title} {description}"
    source_group = str(article.get("source_group", "")).strip().lower()

    if any(phrase in text for phrase in _LOW_SIGNAL_PHRASES):
        return True

    # GDACS "Green" alerts are low-severity informational items and can crowd
    # out more relevant logistics, policy, and severe-weather updates.
    if source_group == "weather_disasters" and title.startswith("green "):
        return True

    return False


def parse_article_datetime(value: object) -> datetime | None:
    """Parse common feed date formats into timezone-aware UTC datetimes."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        raw = value.strip()
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = parsedate_to_datetime(raw)
            except (TypeError, ValueError):
                return None
    else:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def dedupe_articles(articles: list[dict]) -> list[dict]:
    """Remove duplicate URLs and near-identical titles while preserving order."""
    seen_fingerprints: set[str] = set()
    seen_titles: set[str] = set()
    unique: list[dict] = []

    for article in articles:
        fingerprint = article_fingerprint(article)
        title_key = _normalized_title(str(article.get("title", "")))
        if fingerprint in seen_fingerprints or title_key in seen_titles:
            continue
        seen_fingerprints.add(fingerprint)
        if title_key:
            seen_titles.add(title_key)
        enriched = dict(article)
        enriched["fingerprint"] = fingerprint
        unique.append(enriched)

    return unique


def select_fresh_articles(
    articles: list[dict],
    *,
    now: datetime | None = None,
    max_items: int = 30,
    fresh_hours: int = 36,
    fallback_hours: int = 72,
    per_source_limit: int = 4,
    per_group_limit: int = 10,
) -> list[dict]:
    """Select recent articles with source and group diversity caps."""
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    reference = reference.astimezone(timezone.utc)

    fresh: list[tuple[datetime, dict]] = []
    fallback: list[tuple[datetime, dict]] = []
    for article in dedupe_articles(articles):
        if is_low_signal_article(article):
            continue
        published_at = parse_article_datetime(article.get("published"))
        if not published_at:
            continue
        age_hours = (reference - published_at).total_seconds() / 3600
        enriched = dict(article)
        enriched["published_at"] = published_at.isoformat()
        if 0 <= age_hours <= fresh_hours:
            fresh.append((published_at, enriched))
        elif fresh_hours < age_hours <= fallback_hours:
            fallback.append((published_at, enriched))

    ranked = sorted(fresh, key=lambda item: item[0], reverse=True)
    if len(ranked) < max_items:
        ranked.extend(sorted(fallback, key=lambda item: item[0], reverse=True))

    selected: list[dict] = []
    source_counts: dict[str, int] = {}
    group_counts: dict[str, int] = {}
    for _published_at, article in ranked:
        source = str(article.get("source", "Unknown"))
        group = str(article.get("source_group", "unknown"))
        if source_counts.get(source, 0) >= per_source_limit:
            continue
        if group_counts.get(group, 0) >= per_group_limit:
            continue
        selected.append(article)
        source_counts[source] = source_counts.get(source, 0) + 1
        group_counts[group] = group_counts.get(group, 0) + 1
        if len(selected) >= max_items:
            break

    return selected
