"""Markup for the index history chart: pure, no Flask, Dash or database.

The SVG holds only lines and stretches to any width. All text is HTML placed by
percentage over it, so labels stay readable on a phone. Points are normalized to one entry per
consecutive calendar day (missing dates become gaps, the last value wins on a
repeated date). Every interpolated value
is a number, a formatted date or a fixed label.
"""

import json
import math
from datetime import date, timedelta

import config
from components.terminal_data import TIER_COLORS

LIVE_LABEL = "recorded live from here"

CHART_CSS = """
.hchart{overflow:hidden;font-family:'JetBrains Mono',monospace;color:#F2F4F7;background:#07090C;border:1px solid #1D232B;padding:12px 0 8px}
.hchart-wrap{display:flex;margin:0 14px}
.hchart-axis{position:relative;flex:none;width:28px}
.hchart-axis span{position:absolute;right:5px;transform:translateY(-50%);font-size:10px;color:#8A94A3;pointer-events:none}
.hchart-plot{position:relative;flex:1 1 auto;min-width:0;aspect-ratio:16/7;min-height:220px;border:1px solid #1D232B;touch-action:pan-y;cursor:crosshair}
.hchart svg{position:absolute;inset:0;width:100%;height:100%;display:block}
.hchart .line{fill:none;stroke:#F2F4F7;stroke-width:1.25;stroke-linecap:round;stroke-linejoin:round;vector-effect:non-scaling-stroke}
.hchart .tier-rule{stroke:#1D232B;stroke-width:1;stroke-dasharray:3 3;vector-effect:non-scaling-stroke}
.hchart .tier-key{display:flex;flex-wrap:wrap;gap:4px 16px;margin:8px 14px 0 42px;font-size:10px;color:#8A94A3}
.hchart .tier-key b{font-weight:400;letter-spacing:.04em;text-transform:uppercase}
.hchart .year{position:absolute;top:0;bottom:0;border-left:1px solid #1D232B;pointer-events:none}
.hchart .year span{position:absolute;bottom:3px;left:4px;font-size:10px;color:#8A94A3}
.hchart .live{position:absolute;top:0;bottom:0;border-left:1px solid #FFB020;pointer-events:none}
.hchart .live span{position:absolute;top:3px;left:5px;font-size:10px;color:#FFB020;white-space:nowrap}
.hchart .live.to-left span{left:auto;right:5px}
.hchart .mark{position:absolute;transform:translate(-50%,-50%);min-width:18px;height:18px;line-height:16px;text-align:center;font-size:10px;color:#FFB020;background:#000000;border:1px solid #FFB020;text-decoration:none}
.hchart .cursor{position:absolute;top:0;bottom:0;width:0;border-left:1px solid #8A94A3;display:none;pointer-events:none}
.hchart #hchart-readout{margin:8px 14px 0;min-height:1.4em;font-size:12px;color:#F2F4F7}
@media (max-width:600px){.hchart-plot{aspect-ratio:4/3;min-height:240px}.hchart-axis span,.hchart .tier-key,.hchart .year span,.hchart .live span{font-size:9px}}
"""

_SCRIPT = """(function(){
var d=JSON.parse(document.getElementById('hchart-data').textContent);
var plot=document.querySelector('.hchart-plot'),out=document.getElementById('hchart-readout'),cur=plot.querySelector('.cursor');
var M=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
var p=d.start.split('-'),t0=Date.UTC(+p[0],+p[1]-1,+p[2]);
function tier(v){for(var i=0;i<d.tiers.length;i++){if(v>=d.tiers[i].min)return d.tiers[i].label;}return d.tiers[d.tiers.length-1].label;}
function show(e){
var r=plot.getBoundingClientRect(),n=d.values.length;
var x=(e.touches&&e.touches[0]?e.touches[0].clientX:e.clientX)-r.left;
var f=Math.min(1,Math.max(0,x/r.width));
var i=n>1?Math.round(f*(n-1)):0;
var dt=new Date(t0+i*86400000);
var s=dt.getUTCDate()+' '+M[dt.getUTCMonth()]+' '+dt.getUTCFullYear()+' \\u00b7 ';
var v=d.values[i];
out.textContent=s+(v===null?'no value':v.toFixed(1)+' \\u00b7 '+tier(v));
cur.style.left=(n>1?i/(n-1)*100:50)+'%';cur.style.display='block';
}
plot.addEventListener('pointermove',show);
plot.addEventListener('pointerdown',show);
plot.addEventListener('touchmove',show,{passive:true});
plot.addEventListener('pointerleave',function(){cur.style.display='none';});
})();"""


def _num(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _clamp(value: float) -> float:
    return min(100.0, max(0.0, value))


def _path(values: list[float | None], n: int) -> str:
    parts: list[str] = []
    run = 0
    for i, v in enumerate(values):
        if v is None:
            run = 0
            continue
        x = i / (n - 1) * 1000 if n > 1 else 500.0
        y = 100 - v
        if run == 0:
            parts.append(f"M{x:.2f} {y:.2f}")
        else:
            parts.append(f"L{x:.2f} {y:.2f}")
        run += 1
    # A run of one day: "Mx yL..." never follows it, so close it as a zero-length segment.
    out = []
    for k, part in enumerate(parts):
        nxt = parts[k + 1] if k + 1 < len(parts) else "M"
        out.append(part)
        if part.startswith("M") and nxt.startswith("M"):
            out.append("h0")
    return "".join(out)


def _pct(i: int, n: int) -> float:
    return i / (n - 1) * 100 if n > 1 else 50.0


def chart_html(points: list[tuple[date, float | None]], episodes: list[dict], live_from: date) -> str:
    if not points:
        return ""
    # Normalize onto every consecutive calendar day, first to last date. A date not
    # passed becomes a gap; if a date repeats the last value wins. Never raises.
    by_day = {d: v for d, v in points}
    first, last = min(by_day), max(by_day)
    n = (last - first).days + 1
    days = [first + timedelta(days=i) for i in range(n)]
    values = [None if (v := _num(by_day.get(d))) is None else _clamp(v) for d in days]
    tiers = sorted(config.HEALTH_TIERS, key=lambda t: -t["min"])

    rules = "".join(
        f'<line class="tier-rule" x1="0" x2="1000" y1="{100 - t["min"]:.2f}" y2="{100 - t["min"]:.2f}"/>'
        for t in tiers if t["min"] > 0
    )
    levels = [100] + [t["min"] for t in tiers if t["min"] > 0] + [0]
    axis = "".join(f'<span style="top:{100 - v:.2f}%">{v}</span>' for v in levels)
    legend = "".join(
        f'<span class="tk"><b style="color:{TIER_COLORS[t["label"]]}">{t["label"]}</b> {t["min"]} to {t["max"]}</span>'
        for t in tiers
    )
    years = "".join(
        f'<div class="year" style="left:{_pct(i, n):.2f}%"><span>{d.year}</span></div>'
        for i, d in enumerate(days) if d.month == 1 and d.day == 1
    )
    live = ""
    if first <= live_from <= last:
        i = (live_from - first).days
        side = " to-left" if _pct(i, n) > 50 else ""
        live = f'<div class="live{side}" style="left:{_pct(i, n):.2f}%"><span>{LIVE_LABEL}</span></div>'
    marks = []
    for ep in episodes:
        idx, d = _num(ep.get("index")), ep.get("date")
        if idx is None or not isinstance(d, date) or not first <= d <= last:
            continue
        marks.append(
            f'<a class="mark" href="#ep-{int(ep["n"])}" '
            f'style="left:{_pct((d - first).days, n):.2f}%;top:{100 - _clamp(idx):.2f}%">{int(ep["n"])}</a>'
        )
    data = json.dumps({
        "start": first.isoformat(),
        "values": [None if v is None else round(v, 1) for v in values],
        "tiers": [{"min": t["min"], "label": t["label"]} for t in tiers],
    }, separators=(",", ":"))

    return (
        '<div class="hchart">'
        '<div class="hchart-wrap">'
        f'<div class="hchart-axis">{axis}</div>'
        '<div class="hchart-plot">'
        '<svg viewBox="0 0 1000 100" preserveAspectRatio="none" role="img" aria-label="Global index history, 0 to 100">'
        f'{rules}<path class="line" d="{_path(values, n)}"/></svg>'
        f'{years}{live}{"".join(marks)}<div class="cursor"></div>'
        '</div></div>'
        f'<div class="tier-key">{legend}</div>'
        '<p id="hchart-readout"></p>'
        f'<script type="application/json" id="hchart-data">{data}</script>'
        f'<script>{_SCRIPT}</script>'
        '</div>'
    )
