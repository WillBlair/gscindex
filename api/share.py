"""Discovery and sharing: robots.txt, sitemap.xml, the share card image, share tags, analytics.

- ``/robots.txt`` and ``/sitemap.xml`` are real files (before this, Dash's catch-all served
  the dashboard HTML at both paths).
- ``/og.png`` is a 1200x630 card with today's Global index, tier, change vs yesterday and
  the two sector indexes, drawn from the in-memory snapshot. It is cached per snapshot.
- Open Graph and Twitter tags go into the HTML of the public pages. The image URL carries
  the snapshot time, so LinkedIn and X fetch a new card after each update instead of
  reusing an old one.
- The Cloudflare Web Analytics beacon (cookieless) is added to the public pages when
  ``CF_ANALYTICS_TOKEN`` is set and the request came to gscindex.com. Never on
  /unsubscribe, whose URL carries a token.

Numbers come from ``components.terminal_data.index_summary``, the same values the readout
shows. Nothing here fetches data.
"""
from __future__ import annotations

import io
import re
import threading
from datetime import datetime
from typing import Callable

from flask import Flask, Response, request
from markupsafe import escape

from config import APP_TITLE, CF_ANALYTICS_TOKEN, SECTORS, SITE_URL, SITEMAP_PATHS

SnapshotGetter = Callable[[], tuple[dict | None, bool]]

CARD_SIZE = (1200, 630)
_CARD_BG = "#000000"
_CARD_RULE = "#1D232B"
_CARD_AMBER = "#FFB020"
_CARD_TEXT = "#F2F4F7"
_CARD_DIM = "#8A94A3"
# Tier bands on the card's 0–100 scale bar: (low, high, tier label)
_SCALE_BANDS = ((0, 40, "Critical"), (40, 60, "Stressed"), (60, 80, "Stable"), (80, 100, "Healthy"))

_PAGE_TITLES = {
    "/docs": f"Methodology | {APP_TITLE}",
    "/report": f"Daily report | {APP_TITLE}",
}
_DESCRIPTION = ("A daily 0 to 100 health score for global supply chains, built only from "
                "published data: NY Fed GSCPI, chokepoint transits, energy, tariffs, freight, "
                "input costs and port hazards.")
_TOKEN_RE = re.compile(r"[A-Za-z0-9]{16,64}")

_CARD_LOCK = threading.Lock()
_CARD_CACHE: dict[str, bytes] = {}


def robots_txt() -> str:
    return "\n".join([
        "User-agent: *",
        "Disallow: /api/v1/admin/",
        "Disallow: /api/v1/newsletter-data",
        "Disallow: /unsubscribe",
        "Disallow: /_dash-",
        "",
        f"Sitemap: {SITE_URL}/sitemap.xml",
        "",
    ])


def sitemap_xml() -> str:
    urls = "".join(f"<url><loc>{escape(SITE_URL + path)}</loc></url>" for path in SITEMAP_PATHS)
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')


def card_numbers(data: dict | None) -> dict:
    """Global and sector values for the card and share tags, as the readout shows them."""
    from components.terminal_data import DEFAULT_TAB, index_summary

    if not data:
        return {"global": None, "sectors": {}, "updated": None}
    sectors = {key: index_summary(data, key) for key in SECTORS}
    return {"global": index_summary(data, DEFAULT_TAB), "sectors": sectors,
            "updated": data.get("last_updated_utc")}


def _parse_updated(raw) -> datetime | None:
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _version(data: dict | None) -> str:
    """Cache-busting value for the image URL: the snapshot time, digits only."""
    raw = (data or {}).get("last_updated_utc") or ""
    return re.sub(r"\D", "", str(raw))[:12] or "0"


def share_title(numbers: dict) -> str:
    summary = numbers.get("global") or {}
    if summary.get("today") is None or not summary.get("tier"):
        return APP_TITLE
    return f"{APP_TITLE}: {summary['today']:.1f} ({summary['tier']['label']})"


def share_description(numbers: dict) -> str:
    parts = [
        f"{SECTORS[key]['label']} {s['today']:.1f}"
        for key, s in (numbers.get("sectors") or {}).items() if s.get("today") is not None
    ]
    return _DESCRIPTION + (f" Sector indexes: {', '.join(parts)}." if parts else "")


def share_tags(path: str, data: dict | None) -> str:
    numbers = card_numbers(data)
    title = _PAGE_TITLES.get(path) or share_title(numbers)
    description = share_description(numbers)
    image = f"{SITE_URL}/og.png?v={_version(data)}"
    url = SITE_URL + path
    tags = [
        ("property", "og:type", "website"),
        ("property", "og:site_name", APP_TITLE),
        ("property", "og:title", title),
        ("property", "og:description", description),
        ("property", "og:url", url),
        ("property", "og:image", image),
        ("property", "og:image:width", str(CARD_SIZE[0])),
        ("property", "og:image:height", str(CARD_SIZE[1])),
        ("property", "og:image:alt", share_title(numbers)),
        ("name", "twitter:card", "summary_large_image"),
        ("name", "twitter:title", title),
        ("name", "twitter:description", description),
        ("name", "twitter:image", image),
    ]
    html = "".join(f'<meta {attr}="{key}" content="{escape(value)}">' for attr, key, value in tags)
    return html + f'<link rel="canonical" href="{escape(url)}">'


def analytics_tag(token: str | None = None) -> str:
    """Cloudflare beacon, or '' when the token is unset or not a plain alphanumeric token."""
    token = CF_ANALYTICS_TOKEN if token is None else token
    if not _TOKEN_RE.fullmatch(token or ""):
        return ""
    return ("<script type=\"module\" src=\"https://static.cloudflareinsights.com/beacon.min.js\" "
            f"data-cf-beacon='{{\"token\": \"{token}\"}}'></script>")


def _is_public_host(host: str) -> bool:
    """gscindex.com or www.gscindex.com, so local previews never count as visits."""
    site = SITE_URL.split("://", 1)[-1]
    host = (host or "").split(":", 1)[0].lower()
    return host in (site, f"www.{site}")


_SOURCE_PART_RE = re.compile(r"[a-z0-9_-]{1,30}")


def signup_source(search: str | None) -> str | None:
    """'utm_source/utm_campaign' from the page's query string, e.g. 'reddit/test1'.

    Lowercased; a value with anything but letters, digits, '_' or '-' is dropped, so the
    stored source is never free text from the URL.
    """
    from urllib.parse import parse_qs

    params = parse_qs((search or "").lstrip("?"))
    parts = []
    for key in ("utm_source", "utm_campaign"):
        value = (params.get(key) or [""])[0].strip().lower()
        if not _SOURCE_PART_RE.fullmatch(value):
            break
        parts.append(value)
    return "/".join(parts) or None


def _font(size: int):
    from PIL import ImageFont

    # Pillow's bundled FreeType font (Aileron), so the card renders the same on Render
    # as locally with no font file in the repo.
    return ImageFont.load_default(size=size)


def render_card(data: dict | None) -> bytes:
    """PNG bytes of the share card. With no snapshot it shows the title and site only."""
    from PIL import Image, ImageDraw

    from components.terminal_data import TIER_COLORS

    width, height = CARD_SIZE
    img = Image.new("RGB", CARD_SIZE, _CARD_BG)
    draw = ImageDraw.Draw(img)
    margin = 64
    draw.rectangle([24, 24, width - 25, height - 25], outline=_CARD_RULE, width=2)
    draw.text((margin, 60), APP_TITLE.upper(), font=_font(34), fill=_CARD_AMBER)

    numbers = card_numbers(data)
    summary = numbers["global"] or {}
    today, tier = summary.get("today"), summary.get("tier")
    if today is not None and tier:
        color = tier["color"]
        draw.text((margin - 8, 118), f"{today:.1f}", font=_font(230), fill=color,
                  stroke_width=3, stroke_fill=color)
        draw.text((margin, 372), tier["label"].upper(), font=_font(52), fill=color,
                  stroke_width=1, stroke_fill=color)
        change = summary.get("change")
        if change is not None:
            if round(change, 1) == 0:
                change_text = "Unchanged from yesterday"
            else:
                change_text = f"{'Up' if change > 0 else 'Down'} {abs(change):.1f} from yesterday"
            draw.text((margin, 440), change_text, font=_font(32), fill=_CARD_DIM)

        # 0–100 scale with the tier bands and a tick at today's value
        bar_left, bar_right, bar_y = margin, 700, 504
        span = bar_right - bar_left
        for low, high, label in _SCALE_BANDS:
            draw.rectangle([bar_left + span * low / 100, bar_y,
                            bar_left + span * high / 100 - 3, bar_y + 10], fill=TIER_COLORS[label])
        tick_x = bar_left + span * max(0.0, min(100.0, today)) / 100
        draw.rectangle([tick_x - 3, bar_y - 12, tick_x + 3, bar_y + 22], fill=_CARD_TEXT)
    else:
        draw.text((margin, 200), "Index loading", font=_font(80), fill=_CARD_TEXT)

    # Sector column
    col_x = 800
    draw.line([(col_x - 40, 130), (col_x - 40, 470)], fill=_CARD_RULE, width=2)
    y = 140
    for key, s in numbers["sectors"].items():
        draw.text((col_x, y), f"{SECTORS[key]['label'].upper()} INDEX", font=_font(28), fill=_CARD_DIM)
        if s.get("today") is not None and s.get("tier"):
            draw.text((col_x, y + 40), f"{s['today']:.1f}", font=_font(88), fill=s["tier"]["color"],
                      stroke_width=1, stroke_fill=s["tier"]["color"])
        else:
            draw.text((col_x, y + 52), "Not enough data", font=_font(32), fill=_CARD_DIM)
        y += 170

    draw.text((margin, height - 82), SITE_URL.removeprefix("https://"), font=_font(30), fill=_CARD_TEXT)
    updated = _parse_updated(numbers["updated"])
    if updated:
        stamp = f"Updated {updated:%d %b %Y, %H:%M} UTC"
        stamp_font = _font(26)
        stamp_w = draw.textlength(stamp, font=stamp_font)
        draw.text((width - margin - stamp_w, height - 78), stamp, font=stamp_font, fill=_CARD_DIM)

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def card_png(data: dict | None) -> bytes:
    """The card for this snapshot, rendered once per snapshot time."""
    key = _version(data)
    with _CARD_LOCK:
        cached = _CARD_CACHE.get(key)
    if cached is not None:
        return cached
    png = render_card(data)
    with _CARD_LOCK:
        _CARD_CACHE.clear()
        _CARD_CACHE[key] = png
    return png


def _inject(html: str, head: str, body: str) -> str:
    if head:
        html = html.replace("</head>", head + "</head>", 1)
    if body:
        html = html.replace("</body>", body + "</body>", 1)
    return html


def register_share_routes(server: Flask, get_snapshot: SnapshotGetter) -> None:
    """robots.txt, sitemap.xml, /og.png, and share tags plus analytics on the public pages."""

    @server.get("/robots.txt")
    def robots():
        return Response(robots_txt(), mimetype="text/plain")

    @server.get("/sitemap.xml")
    def sitemap():
        return Response(sitemap_xml(), mimetype="application/xml")

    @server.get("/og.png")
    def share_card():
        data, _ = get_snapshot()
        resp = Response(card_png(data), mimetype="image/png")
        # The URL changes with each snapshot, so an hour of caching never shows an old score.
        resp.headers["Cache-Control"] = "public, max-age=3600"
        return resp

    @server.after_request
    def add_share_tags(response):
        if (request.method != "GET" or request.path not in SITEMAP_PATHS
                or response.status_code != 200 or response.mimetype != "text/html"
                or response.direct_passthrough):
            return response
        data, _ = get_snapshot()
        html = response.get_data(as_text=True)
        beacon = analytics_tag() if _is_public_host(request.host) else ""
        response.set_data(_inject(html, share_tags(request.path, data), beacon))
        return response
