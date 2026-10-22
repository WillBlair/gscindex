"""
LLM Client
==========
Thin wrapper around the Anthropic API shared by every AI-powered component
(news analysis, briefings, report, score explanation, port summaries).

Callers check ``is_configured()`` and keep their own deterministic fallbacks;
``complete_text`` / ``complete_json`` raise ``LLMError`` on any failure so
each caller decides what to fall back to.
"""
from __future__ import annotations

import json
import logging
import os

import anthropic
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
# Sonnet 5.5 defaults to "high"; these are short summarization/scoring jobs.
EFFORT = os.environ.get("ANTHROPIC_EFFORT", "medium")
MAX_TOKENS = 16000

# Server-side retry on another model if a safety classifier declines.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

_client: anthropic.Anthropic | None = None


class LLMError(RuntimeError):
    """The model call failed, was refused, or returned unusable output."""


def is_configured() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        # Bounded like the rest of the refresh work: one attempt, no hung threads.
        _client = anthropic.Anthropic(timeout=90.0, max_retries=0)
    return _client


def _create(prompt: str, system: str | None, output_format: dict | None) -> str:
    if not is_configured():
        raise LLMError("ANTHROPIC_API_KEY not set")

    output_config: dict = {"effort": EFFORT}
    if output_format is not None:
        output_config["format"] = output_format

    kwargs: dict = {}
    if system:
        kwargs["system"] = system

    try:
        response = _get_client().beta.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
            output_config=output_config,
            betas=[_FALLBACK_BETA],
            fallbacks="default",
            **kwargs,
        )
    except anthropic.APIConnectionError as exc:
        raise LLMError(f"network error: {exc}") from exc
    except anthropic.RateLimitError as exc:
        raise LLMError(f"rate limited: {exc.message}") from exc
    except anthropic.APIStatusError as exc:
        raise LLMError(f"API error {exc.status_code}: {exc.message}") from exc

    if response.stop_reason == "refusal":
        category = getattr(response.stop_details, "category", None)
        raise LLMError(f"model declined (category={category})")
    if response.stop_reason == "max_tokens":
        raise LLMError("response truncated at max_tokens")

    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        raise LLMError("empty response")
    return text


def complete_text(prompt: str, *, system: str | None = None) -> str:
    """Return the model's plain-text reply."""
    return _create(prompt, system, None)


def complete_json(prompt: str, *, schema: dict, system: str | None = None):
    """Return the model's reply parsed as JSON, constrained to ``schema``."""
    text = _create(prompt, system, {"type": "json_schema", "schema": schema})
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"invalid JSON from model: {exc}") from exc
