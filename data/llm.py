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

# Web search (server tool, runs on Anthropic's side; billed per search on top
# of tokens). Turn off with AI_WEB_SEARCH=0.
WEB_SEARCH_ENABLED = os.environ.get("AI_WEB_SEARCH", "1") != "0"
_WEB_SEARCH_TIMEOUT = 240.0
_MAX_CONTINUATIONS = 4

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


def research_json(
    prompt: str,
    *,
    schema: dict,
    system: str | None = None,
    max_searches: int = 5,
    submit_tool: str = "submit_results",
    submit_description: str = "Submit the final results. Call exactly once, at the end.",
) -> dict:
    """Let the model search the web, then return its answer as validated JSON.

    Structured output formats can't be combined with search citations, so the
    answer comes back through a strict ``submit_tool`` call instead. Server-side
    search loops can stop with ``pause_turn``; the turn is resent unchanged so
    the server resumes it.
    """
    if not is_configured():
        raise LLMError("ANTHROPIC_API_KEY not set")

    tools = [
        {"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches},
        {
            "name": submit_tool,
            "description": submit_description,
            "input_schema": schema,
            "strict": True,
        },
    ]
    kwargs: dict = {"system": system} if system else {}
    messages: list[dict] = [{"role": "user", "content": prompt}]
    client = _get_client().with_options(timeout=_WEB_SEARCH_TIMEOUT)

    for _ in range(_MAX_CONTINUATIONS + 1):
        try:
            response = client.beta.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                messages=messages,
                tools=tools,
                output_config={"effort": EFFORT},
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

        for block in response.content:
            if block.type == "tool_use" and block.name == submit_tool:
                if not isinstance(block.input, dict):
                    raise LLMError("submit tool returned non-object input")
                return block.input

        if response.stop_reason == "pause_turn":
            # Resend the turn so far, unchanged, as the trailing assistant
            # message; the server resumes it and returns the continuation.
            assistant_blocks = list(messages[1]["content"]) if len(messages) > 1 else []
            assistant_blocks.extend(response.content)
            messages = [messages[0], {"role": "assistant", "content": assistant_blocks}]
            continue
        raise LLMError(f"model finished without calling {submit_tool} ({response.stop_reason})")

    raise LLMError("web search did not finish within the continuation limit")
