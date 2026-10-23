"""Snapshot helpers shared by the Terminal panes: safe text and links, news selection, CSV export."""
from __future__ import annotations

import csv
import io
import math
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

from components.terminal_data import sector_block, tab_key, tab_weights
from config import BOJ_CREDIT, CATEGORY_LABELS, DEFAULT_TAB, SECTORS
from data.providers.chokepoints import CREDIT as PORTWATCH_CREDIT
from data.providers.semis import BOJ_CATEGORIES


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


def finite_score(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def select_news(alerts, query="", severity="all", category="all"):
    query = (query or "").strip().casefold()
    selected = [a for a in alerts if (severity == "all" or a.get("severity") == severity)
                and (category == "all" or a.get("category") == category)
                and query in plain_text(" ".join(str(a.get(k) or "") for k in ("title", "body", "source"))).casefold()]
    return sorted(selected, key=lambda a: str(a.get("timestamp") or ""), reverse=True)


def _csv_status(available, cat, meta, flags):
    """excluded / missing / fallback / stale / measured. ``flags`` holds the tab's own lists
    (the snapshot for Global, the sector block for a sector)."""
    if not available:
        return "excluded" if cat in (flags.get("excluded_categories") or []) else "missing"
    if meta.get("is_fallback"):
        return "fallback"
    if meta.get("is_stale") or cat in (flags.get("stale_categories") or []):
        return "stale"
    return "measured"


# Attribution a row must carry: chokepoint transits and the port-call shares behind the
# physical hazard score come from IMF PortWatch.
_CSV_CREDITS = {"chokepoints": PORTWATCH_CREDIT, "physical": PORTWATCH_CREDIT}
# The Global export keeps its pre-tab profile name so its file is unchanged.
_GLOBAL_PROFILE_LABEL = "Baseline (Global)"
# Rows built from BOJ data (the providers' ``credits_boj`` flag) carry the Bank of Japan credit
# line and its reuse terms.
SEMIS_CSV_TERMS = (BOJ_CREDIT + " Commercial reuse of the memory and logic scores requires the "
                   "Bank of Japan's permission.")


def _inputs_cell(meta):
    """'boj_memory 72.3 as of 2026-08-31 (live); ...' from the category's inputs metadata."""
    parts = []
    for item in meta.get("inputs") or []:
        if not isinstance(item, dict):
            continue
        score = item.get("score")
        score = f"{score:g}" if finite_score(score) else "missing"
        parts.append(f"{item.get('name') or 'input'} {score} as of {item.get('as_of') or 'unknown'} "
                     f"({item.get('status') or 'unknown'})")
    return "; ".join(parts)


def snapshot_csv(data, key):
    """A tab-scoped export with provenance, data date (as_of) and freshness status.

    Sector exports add an ``inputs`` column; rows built from BOJ data carry the BOJ credit and terms.
    """
    key = tab_key(key)
    sector = key != DEFAULT_TAB
    flags = sector_block(data, key) if sector else data
    label = SECTORS[key]["title"] if sector else _GLOBAL_PROFILE_LABEL
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    header = ["snapshot_utc", "profile", "category", "score", "weight", "weighted_points", "status", "as_of", "source", "source_updated", "credit"]
    writer.writerow(header + ["inputs"] if sector else header)
    def cell(value):
        value = str(value or "")
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
    for cat, weight in tab_weights(key).items():
        score = data.get("current_scores", {}).get(cat)
        meta = data.get("category_metadata", {}).get(cat, {})
        available = finite_score(score)
        credit = SEMIS_CSV_TERMS if cat in BOJ_CATEGORIES else _CSV_CREDITS.get(cat, "")
        row = [cell(data.get("last_updated_utc")), cell(label), CATEGORY_LABELS.get(cat, cat),
               score if available else "", weight, round(score * weight, 3) if available else "",
               _csv_status(available, cat, meta, flags), cell(meta.get("as_of")),
               cell(meta.get("source")), cell(meta.get("updated")), credit]
        writer.writerow(row + [cell(_inputs_cell(meta))] if sector else row)
    return output.getvalue()
