"""Relative-time formatting for headline ages."""

from __future__ import annotations

from datetime import datetime, timezone


def _format_time_ago(iso_timestamp: str, *, now: datetime | None = None) -> str:
    """Convert an ISO timestamp to a human-readable 'X hours ago' string.

    Handles both timezone-aware (NewsAPI sends ``Z`` suffix) and
    timezone-naive timestamps gracefully.
    """
    try:
        dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return "recently"

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    current_time = now if now is not None else datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)

    diff = current_time.astimezone(timezone.utc) - dt.astimezone(timezone.utc)
    total_seconds = diff.total_seconds()

    if total_seconds < 0:
        return "just now"
    if total_seconds < 3600:
        return f"{int(total_seconds / 60)}m ago"
    if total_seconds < 86400:
        return f"{int(total_seconds / 3600)}h ago"
    return f"{int(total_seconds / 86400)}d ago"
