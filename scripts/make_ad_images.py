"""Draw the Reddit ad images for the daily briefing (offline; not used by the site).

Square 1080x1080 for the mobile feed and wide 1200x628 for desktop: a dot world map with
every port the site scores, colored by its score, today's index and a "sign up free" bar.
Every number comes from the live /api/v1/latest response (or a saved copy of it):

    venv/bin/python scripts/make_ad_images.py                    # fetches gscindex.com
    venv/bin/python scripts/make_ad_images.py --latest latest.json

Writes docs/ads/reddit-square-<date>.png and docs/ads/reddit-wide-<date>.png.
Assets in docs/ads/assets: Natural Earth 110m land (world-atlas topojson, public domain),
Inter and JetBrains Mono (SIL Open Font License, see the OFL files).
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components.terminal_data import TIER_COLORS, tier_for  # noqa: E402
from config import SCORE_ANCHORS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "ads" / "assets"
OUT_DIR = ROOT / "docs" / "ads"
LATEST_URL = "https://gscindex.com/api/v1/latest"

BG, PANE, RULE = "#000000", "#07090C", "#1D232B"
AMBER, TEXT, DIM, LAND = "#FFB020", "#F2F4F7", "#8A94A3", "#2A323D"
LAT_TOP, LAT_BOTTOM = 74.0, -50.0  # cropped to the land around the ports (none past these)
LON_LEFT, LON_RIGHT = -135.0, 167.0
MAP_RATIO = (LAT_TOP - LAT_BOTTOM) / (LON_RIGHT - LON_LEFT)


def _font(size, weight=700, mono=False):
    font = ImageFont.truetype(str(ASSETS / ("JetBrainsMono.ttf" if mono else "Inter.ttf")), size)
    font.set_variation_by_axes([weight] if mono else [min(32, max(14, size)), weight])
    return font


def _land_rings():
    """Decode the topojson land arcs into lon/lat rings."""
    topo = json.loads((ASSETS / "land-110m.json").read_text())
    (sx, sy), (tx, ty) = topo["transform"]["scale"], topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        points = []
        for dx, dy in arc:
            x, y = x + dx, y + dy
            points.append((x * sx + tx, y * sy + ty))
        arcs.append(points)

    def ring(indexes):
        points = []
        for i in indexes:
            part = arcs[i] if i >= 0 else arcs[~i][::-1]
            points.extend(part if not points else part[1:])
        return points

    rings = []
    for geom in topo["objects"]["land"]["geometries"]:
        polygons = geom["arcs"] if geom["type"] == "MultiPolygon" else [geom["arcs"]]
        for polygon in polygons:
            rings.extend(ring(r) for r in polygon)
    return rings


def _project(lon, lat, box):
    x0, y0, x1, y1 = box
    return (x0 + (lon - LON_LEFT) / (LON_RIGHT - LON_LEFT) * (x1 - x0),
            y0 + (LAT_TOP - lat) / (LAT_TOP - LAT_BOTTOM) * (y1 - y0))


def _dot_map(img, box, markers, step):
    """Land as a grid of dots, then every scored port in its tier color."""
    x0, y0, x1, y1 = box
    w, h = int(x1 - x0), int(y1 - y0)
    mask = Image.new("1", (w, h), 0)
    mdraw = ImageDraw.Draw(mask)
    for ring in _land_rings():  # even-odd fill: holes (lakes) are inner rings
        pts = [_project(lon, lat, (0, 0, w, h)) for lon, lat in ring]
        if len(pts) > 2:
            mdraw.polygon(pts, fill=1)
    draw = ImageDraw.Draw(img)
    r = step * 0.30
    for gy in range(step // 2, h, step):
        for gx in range(step // 2, w, step):
            if mask.getpixel((gx, gy)):
                draw.ellipse([x0 + gx - r, y0 + gy - r, x0 + gx + r, y0 + gy + r], fill=LAND)
    for m in sorted(markers, key=lambda m: -m["score"]):  # worst drawn last, on top
        cx, cy = _project(m["lon"], m["lat"], box)
        pr = step * (0.95 if m["score"] < 40 else 0.7)
        draw.ellipse([cx - pr - 3, cy - pr - 3, cx + pr + 3, cy + pr + 3], fill=BG)
        draw.ellipse([cx - pr, cy - pr, cx + pr, cy + pr], fill=tier_for(m["score"])["color"])


def _label_worst(draw, box, markers, size):
    m = min(markers, key=lambda m: m["score"])
    cx, cy = _project(m["lon"], m["lat"], box)
    label = f"{m['name']} {m['score']:.0f}"
    font = _font(size, 700, mono=True)
    w = draw.textlength(label, font=font)
    tx, ty = cx + size * 0.9, cy - size * 2.2
    draw.line([(cx + 4, cy - 4), (tx - 4, ty + size * 0.6)], fill=TEXT, width=2)
    draw.rectangle([tx - 8, ty - 6, tx + w + 8, ty + size + 8], fill=BG, outline=RULE, width=2)
    draw.text((tx, ty - size * 0.1), label, font=font, fill=tier_for(m["score"])["color"])


def _score_chip(draw, xy, score, size):
    x, y = xy
    tier = tier_for(score)
    _small = _font(int(size * 0.34), 500, mono=True)
    draw.text((x, y), "TODAY'S INDEX", font=_small, fill=DIM)
    big = _font(size, 800, mono=True)
    draw.text((x - 2, y + size * 0.42), f"{score:.1f}", font=big, fill=tier["color"])
    w = draw.textlength(f"{score:.1f}", font=big)
    draw.text((x + w + size * 0.22, y + size * 0.92), tier["label"].upper(),
              font=_font(int(size * 0.36), 700, mono=True), fill=tier["color"])


def _legend(draw, xy, size, align_right=False):
    font = _font(size, 500, mono=True)
    labels = ("Healthy", "Stable", "Stressed", "Critical")
    width = sum(size * 2.05 + draw.textlength(label, font=font) for label in labels) - size * 1.1
    x, y = xy
    if align_right:
        x -= width
    for label in labels:
        draw.ellipse([x, y + size * 0.25, x + size * 0.7, y + size * 0.95], fill=TIER_COLORS[label])
        x += size * 0.95
        draw.text((x, y), label, font=font, fill=DIM)
        x += draw.textlength(label, font=font) + size * 1.1


def _coverage(data):
    ports, corridors = len(data["map_markers"]), len(SCORE_ANCHORS["chokepoint_weights"])
    return f"{ports} ports and {corridors} chokepoints"


def _free_badge(draw, xy, size):
    x, y = xy
    font = _font(size, 900)
    w = draw.textlength("FREE", font=font)
    draw.rectangle([x, y, x + w + size * 0.6, y + size * 1.25], fill=AMBER)
    draw.text((x + size * 0.3, y + size * 0.05), "FREE", font=font, fill=BG)
    return x + w + size * 0.6


def _cta(draw, box, size):
    x0, y0, x1, y1 = box
    draw.rectangle(box, fill=AMBER)
    bold, reg = _font(size, 800), _font(size, 500)
    left, right = "Sign up free", "  gscindex.com/briefing"
    w = draw.textlength(left, font=bold) + draw.textlength(right, font=reg)
    x, y = x0 + (x1 - x0 - w) / 2, y0 + (y1 - y0) / 2 - size * 0.62
    draw.text((x, y), left, font=bold, fill=BG)
    draw.text((x + draw.textlength(left, font=bold), y), right, font=reg, fill=BG)


def square(data) -> Image.Image:
    img = Image.new("RGB", (1080, 1080), BG)
    draw = ImageDraw.Draw(img)
    m = 64
    right = _free_badge(draw, (m, 60), 40)
    draw.text((right + 18, 66), "daily supply chain email", font=_font(34, 500), fill=TEXT)
    y = 148
    for line in ("The world's supply chain,", "scored every day."):
        draw.text((m, y), line, font=_font(76, 800), fill=TEXT)
        y += 88
    draw.text((m, y + 10), f"{_coverage(data).capitalize()}, in one email.", font=_font(34, 500), fill=DIM)
    map_box = (16, 380, 1064, 380 + 1048 * MAP_RATIO)
    _dot_map(img, map_box, data["map_markers"], 12)
    _label_worst(draw, map_box, data["map_markers"], 24)
    _score_chip(draw, (m, 818), data["composite_index"], 70)
    _legend(draw, (1080 - m, 900), 21, align_right=True)
    _cta(draw, (m, 962, 1080 - m, 1036), 36)
    return img


def wide(data) -> Image.Image:
    img = Image.new("RGB", (1200, 628), BG)
    draw = ImageDraw.Draw(img)
    m = 48
    right = _free_badge(draw, (m, 48), 30)
    draw.text((right + 14, 52), "daily supply chain email", font=_font(26, 500), fill=TEXT)
    y = 118
    for line in ("The world's", "supply chain, scored", "every day."):
        draw.text((m, y), line, font=_font(46, 800), fill=TEXT)
        y += 56
    draw.text((m, y + 8), f"{_coverage(data).capitalize()}.", font=_font(24, 500), fill=DIM)
    _score_chip(draw, (m, 372), data["composite_index"], 56)
    _cta(draw, (m, 628 - m - 66, 520, 628 - m), 26)
    map_box = (540, 110, 1196, 110 + 656 * MAP_RATIO)
    _dot_map(img, map_box, data["map_markers"], 10)
    _label_worst(draw, map_box, data["map_markers"], 20)
    _legend(draw, (1200 - m, 628 - m - 40), 18, align_right=True)
    return img


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--latest", help="a saved /api/v1/latest response (default: fetch the live one)")
    args = parser.parse_args(argv)
    if args.latest:
        data = json.loads(Path(args.latest).read_text())
    else:
        with urllib.request.urlopen(LATEST_URL, timeout=30) as reply:
            data = json.loads(reply.read())
    if data.get("composite_index") is None or not data.get("map_markers"):
        raise SystemExit("no composite or map markers in the response")
    stamp = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00")).strftime("%Y-%m-%d")
    for name, build in (("square", square), ("wide", wide)):
        path = OUT_DIR / f"reddit-{name}-{stamp}.png"
        build(data).save(path, optimize=True)
        print(path)


if __name__ == "__main__":
    main()
