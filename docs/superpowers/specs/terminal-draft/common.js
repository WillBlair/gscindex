// Shared data + math for the three mockups. Real production snapshot in data.json.
window.GSC = (function () {
  let D = null;

  async function load() {
    D = await (await fetch("data.json")).json();
    return D;
  }

  function tier(score) {
    for (const t of D.tiers) if (score >= t.min) return t;
    return D.tiers[D.tiers.length - 1];
  }

  function profileWeights(key) {
    return D.profiles[key].weights;
  }

  function composite(scores, weights) {
    let total = 0;
    for (const [cat, w] of Object.entries(weights)) total += w * (scores[cat] ?? 50);
    return total;
  }

  // Rows for the change table: yesterday, today, change, weighted effect.
  function rows(profileKey) {
    const w = profileWeights(profileKey);
    const out = Object.entries(w).map(([cat, weight]) => {
      const today = D.scores[cat];
      const yday = D.yesterday[cat];
      const change = today - yday;
      return {
        cat,
        label: D.labels[cat] || cat,
        weight,
        yday,
        today,
        change,
        effect: change * weight,
        hist: (D.history[cat] || []).slice(-30),
        meta: D.meta[cat] || {},
      };
    });
    out.sort((a, b) => b.weight - a.weight);
    return out;
  }

  function summary(profileKey) {
    const w = profileWeights(profileKey);
    const today = composite(D.scores, w);
    const yday = composite(D.yesterday, w);
    return { today, yday, change: today - yday, tier: tier(today) };
  }

  // Index per day from stored category history (days missing a category are skipped).
  function compositeHistory(profileKey) {
    const w = profileWeights(profileKey);
    const n = D.dates.length;
    const out = [];
    for (let i = 0; i < n; i++) {
      let total = 0, ok = true;
      for (const [cat, wt] of Object.entries(w)) {
        const v = (D.history[cat] || [])[i];
        if (v === null || v === undefined) { ok = false; break; }
        total += wt * v;
      }
      out.push(ok ? total : null);
    }
    out[n - 1] = summary(profileKey).today;
    return out;
  }

  function fmt(n, d = 1) {
    return Number(n).toFixed(d);
  }

  function signed(n, d = 1) {
    const v = Number(n);
    if (Math.abs(v) < 0.05) return "0.0";
    return (v > 0 ? "+" : "−") + Math.abs(v).toFixed(d);
  }

  function sparkline(values, { w = 120, h = 28, stroke = "currentColor" } = {}) {
    const pts = values.map((v, i) => [i, v]).filter(([, v]) => v !== null && v !== undefined);
    if (pts.length < 2) return `<svg width="${w}" height="${h}" aria-hidden="true"></svg>`;
    const n = values.length - 1 || 1;
    const ys = pts.map(([, v]) => v);
    let lo = Math.min(...ys), hi = Math.max(...ys);
    if (hi - lo < 4) { const m = (hi + lo) / 2; lo = m - 2; hi = m + 2; }
    const x = (i) => (i / n) * (w - 4) + 2;
    const y = (v) => h - 2 - ((v - lo) / (hi - lo)) * (h - 4);
    const d = pts.map(([i, v], k) => `${k ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    const [li, lv] = pts[pts.length - 1];
    return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true">
      <path d="${d}" fill="none" stroke="${stroke}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>
      <circle cx="${x(li).toFixed(1)}" cy="${y(lv).toFixed(1)}" r="2.2" fill="${stroke}"/></svg>`;
  }

  function briefingBullets() {
    return (D.briefing || "")
      .split("\n")
      .map((l) => l.replace(/^[\s•*-]+/, "").trim())
      .filter(Boolean);
  }

  function topAlerts(n = 8) {
    const rank = { high: 0, medium: 1, low: 2 };
    return [...D.alerts]
      .sort((a, b) => (rank[a.severity] ?? 3) - (rank[b.severity] ?? 3))
      .slice(0, n);
  }

  function relTime(ts) {
    if (!ts) return "";
    const t = Date.parse(ts);
    if (isNaN(t)) return ts;
    const h = Math.round((Date.now() - t) / 3.6e6);
    if (h < 1) return "just now";
    if (h < 24) return `${h}h ago`;
    return `${Math.round(h / 24)}d ago`;
  }

  function cleanSource(s) {
    return String(s || "").replace(/\s*\(web search\)$/, "");
  }

  function updatedLabel() {
    const t = Date.parse(D.updated);
    const mins = Math.max(1, Math.round((Date.now() - t) / 60000));
    return mins < 90 ? `Updated ${mins} min ago` : `Updated ${new Date(t).toUTCString().slice(5, 22)} UTC`;
  }

  function drawMap(el, { land, ocean, coast, border, font, colorFor, bg, hoverBg, hoverFg, height }) {
    const m = D.markers;
    Plotly.newPlot(
      el,
      [{
        type: "scattergeo",
        lat: m.map((p) => p.lat),
        lon: m.map((p) => p.lon),
        text: m.map((p) => `${p.name}: ${Math.round(p.score)}`),
        hoverinfo: "text",
        mode: "markers",
        marker: {
          size: m.map((p) => 7 + (100 - p.score) / 9),
          color: m.map((p) => colorFor(p.score)),
          line: { width: 1, color: bg },
          opacity: 0.95,
        },
      }],
      {
        geo: {
          projection: { type: "natural earth" },
          showland: true, landcolor: land,
          showocean: true, oceancolor: ocean,
          showcountries: true, countrycolor: border,
          showcoastlines: true, coastlinecolor: coast,
          showframe: false, bgcolor: bg,
          lataxis: { range: [-50, 72] },
        },
        margin: { l: 0, r: 0, t: 0, b: 0 },
        paper_bgcolor: bg,
        font: { family: font },
        hoverlabel: { font: { family: font, color: hoverFg }, bgcolor: hoverBg, bordercolor: hoverBg },
        dragmode: false,
      },
      { displayModeBar: false, responsive: true }
    );
  }

  return {
    load, tier, rows, summary, compositeHistory, fmt, signed, sparkline, briefingBullets,
    topAlerts, relTime, cleanSource, updatedLabel, drawMap,
    get data() { return D; },
  };
})();
