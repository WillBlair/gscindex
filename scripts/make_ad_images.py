"""Draw the Reddit ad images for the daily briefing (offline; not used by the site).

Square 1080x1080 for the mobile feed and wide 1200x628 for desktop, in the Terminal look.
The score, date and briefing lines are passed in so every number on the image is one the
site actually showed that day:

    venv/bin/python scripts/make_ad_images.py --score 46.5 --date "28 Oct 2026" \\
        --line "Hormuz transits running at about 60% of normal" \\
        --line "LA/Long Beach strike threatens West Coast gateways" \\
        --line "Transpacific container rates climb to $8,368/FEU"

Writes docs/ads/reddit-square-<date>.png and docs/ads/reddit-wide-<date>.png.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.share import _font  # noqa: E402  (Pillow's bundled font, as on the share card)
from components.terminal_data import tier_for  # noqa: E402

BG, PANE, RULE = "#000000", "#07090C", "#1D232B"
AMBER, TEXT, DIM, BODY = "#FFB020", "#F2F4F7", "#8A94A3", "#D6DBE3"
OUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "ads"


def _wrap(draw, text, font, width):
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    return lines + ([line] if line else [])


def _text(draw, xy, text, size, fill, bold=False):
    draw.text(xy, text, font=_font(size), fill=fill,
              stroke_width=max(1, size // 40) if bold else 0, stroke_fill=fill)


def _email_pane(draw, box, score, date, lines, scale=1.0):
    """Today's score and tier on the 0 to 100 scale, then lines from today's briefing."""
    from components.terminal_data import TIER_COLORS

    x0, y0, x1, y1 = box
    s = lambda n: int(n * scale)
    draw.rectangle(box, fill=PANE, outline=RULE, width=2)
    pad = s(40)
    _text(draw, (x0 + pad, y0 + s(32)), f"TODAY'S BRIEFING  |  {date.upper()}", s(26), DIM)
    tier = tier_for(score)
    _text(draw, (x0 + pad - s(4), y0 + s(74)), f"{score:.1f}", s(130), tier["color"], bold=True)
    num_w = draw.textlength(f"{score:.1f}", font=_font(s(130)))
    _text(draw, (x0 + pad + num_w + s(26), y0 + s(140)), tier["label"].upper(), s(44), tier["color"], bold=True)

    # 0 to 100 scale with the tier bands and a tick at today's score, as on the share card
    bar_x0, bar_x1, bar_y = x0 + pad, x1 - pad, y0 + s(250)
    span = bar_x1 - bar_x0
    for low, high, label in ((0, 40, "Critical"), (40, 60, "Stressed"), (60, 80, "Stable"), (80, 100, "Healthy")):
        draw.rectangle([bar_x0 + span * low / 100, bar_y, bar_x0 + span * high / 100 - s(4), bar_y + s(10)],
                       fill=TIER_COLORS[label])
    tick = bar_x0 + span * score / 100
    draw.rectangle([tick - s(3), bar_y - s(12), tick + s(3), bar_y + s(22)], fill=TEXT)

    y = bar_y + s(62)
    font = _font(s(34))
    for line in lines:
        draw.rectangle([x0 + pad, y + s(14), x0 + pad + s(11), y + s(25)], fill=AMBER)
        for part in _wrap(draw, line, font, x1 - x0 - pad * 2 - s(32)):
            draw.text((x0 + pad + s(32), y), part, font=font, fill=BODY)
            y += s(44)
        y += s(20)
        if y > y1 - s(44):
            break


def _cta(draw, box, size):
    x0, y0, x1, y1 = box
    draw.rectangle(box, fill=AMBER)
    label = "Get it free at gscindex.com/briefing"
    font = _font(size)
    w = draw.textlength(label, font=font)
    draw.text((x0 + (x1 - x0 - w) / 2, y0 + (y1 - y0 - size) / 2 - 4), label, font=font, fill=BG,
              stroke_width=1, stroke_fill=BG)


def square(score, date, lines) -> Image.Image:
    img = Image.new("RGB", (1080, 1080), BG)
    draw = ImageDraw.Draw(img)
    m = 72
    _text(draw, (m, 64), "FREE DAILY BRIEFING", 30, AMBER)
    y = 116
    for line in _wrap(draw, "Global supply chain stress, scored every day.", _font(76), 1080 - 2 * m):
        _text(draw, (m, y), line, 76, TEXT, bold=True)
        y += 88
    _email_pane(draw, (m, y + 32, 1080 - m, 896), score, date, lines)
    _cta(draw, (m, 932, 1080 - m, 1016), 38)
    return img


def wide(score, date, lines) -> Image.Image:
    img = Image.new("RGB", (1200, 628), BG)
    draw = ImageDraw.Draw(img)
    m = 56
    _text(draw, (m, 56), "FREE DAILY BRIEFING", 24, AMBER)
    y = 100
    for line in _wrap(draw, "Global supply chain stress, scored every day.", _font(58), 500):
        _text(draw, (m, y), line, 58, TEXT, bold=True)
        y += 68
    _text(draw, (m, y + 18), "One email a day: a 0 to 100 score", 26, DIM)
    _text(draw, (m, y + 52), "and the news behind it.", 26, DIM)
    _cta(draw, (m, 628 - m - 72, 560, 628 - m), 26)
    _email_pane(draw, (600, m, 1200 - m, 628 - m), score, date, lines, scale=0.74)
    return img


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--score", type=float, required=True)
    parser.add_argument("--date", required=True, help='as shown on the image, e.g. "28 Oct 2026"')
    parser.add_argument("--line", action="append", required=True, help="a briefing line (up to 3)")
    args = parser.parse_args(argv)
    stamp = datetime.strptime(args.date, "%d %b %Y").strftime("%Y-%m-%d")
    for name, build in (("square", square), ("wide", wide)):
        path = OUT_DIR / f"reddit-{name}-{stamp}.png"
        build(args.score, args.date, args.line[:3]).save(path, optimize=True)
        print(path)


if __name__ == "__main__":
    main()
