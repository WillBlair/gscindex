"""Snapshot helpers shared by the Terminal panes: safe text and links, news selection, CSV export."""
from __future__ import annotations

import csv
import io
import math
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

from config import CATEGORY_LABELS, DEFAULT_PROFILE, INDUSTRY_PROFILES
from data.providers.chokepoints import CREDIT as PORTWATCH_CREDIT


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"br", "p", "div", "li"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        elif tag in {"p", "div", "li"}:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value):
    """Strip RSS markup without ever rendering publisher HTML."""
    parser = _PlainText()
    parser.feed(str(value or ""))
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()


def safe_url(value):
    try:
        parsed = urlsplit(str(value or ""))
        return value if parsed.scheme in {"http", "https"} and parsed.netloc else None
    except ValueError:
        return None


def profile_for(key):
    return INDUSTRY_PROFILES.get(key, INDUSTRY_PROFILES[DEFAULT_PROFILE])


def finite_score(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def select_news(alerts, query="", severity="all", category="all"):
    query = (query or "").strip().casefold()
    selected = [a for a in alerts if (severity == "all" or a.get("severity") == severity)
                and (category == "all" or a.get("category") == category)
                and query in plain_text(" ".join(str(a.get(k) or "") for k in ("title", "body", "source"))).casefold()]
    return sorted(selected, key=lambda a: str(a.get("timestamp") or ""), reverse=True)


def _csv_status(available, cat, meta, data):
    """excluded / missing / fallback / stale / measured."""
    if not available:
        return "excluded" if cat in (data.get("excluded_categories") or []) else "missing"
    if meta.get("is_fallback"):
        return "fallback"
    if meta.get("is_stale") or cat in (data.get("stale_categories") or []):
        return "stale"
    return "measured"


# Attribution a row must carry: chokepoint transits and the port-call shares behind the
# physical hazard score come from IMF PortWatch.
_CSV_CREDITS = {"chokepoints": PORTWATCH_CREDIT, "physical": PORTWATCH_CREDIT}


def snapshot_csv(data, key):
    """A profile-scoped export with provenance, data date (as_of) and freshness status."""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["snapshot_utc", "profile", "category", "score", "weight", "weighted_points", "status", "as_of", "source", "source_updated", "credit"])
    def cell(value):
        value = str(value or "")
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
    for cat, weight in profile_for(key)["weights"].items():
        score = data.get("current_scores", {}).get(cat)
        meta = data.get("category_metadata", {}).get(cat, {})
        available = finite_score(score)
        writer.writerow([cell(data.get("last_updated_utc")), cell(profile_for(key)["label"]), CATEGORY_LABELS.get(cat, cat),
                         score if available else "", weight, round(score * weight, 3) if available else "",
                         _csv_status(available, cat, meta, data), cell(meta.get("as_of")),
                         cell(meta.get("source")), cell(meta.get("updated")), _CSV_CREDITS.get(cat, "")])
    return output.getvalue()
