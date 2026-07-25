/**
 * border-beam "pulse-inner" breathing driver — hand-ported to vanilla JS.
 *
 * border-beam (MIT, © Jakub Antalik, https://github.com/Jakubantalik/border-beam)
 * generates its "pulse" styles as *pure CSS* (see border-beam-pulse.css,
 * generated straight from the real package via SSR) but drives the slow
 * "breathing" motion with a small requestAnimationFrame loop that writes
 * plain CSS custom properties — the package's own README documents this as
 * intentionally framework-agnostic: "a single shared, frame-rate-capped
 * (~30fps) requestAnimationFrame loop that writes plain CSS custom
 * properties... works even without @property support." That loop isn't
 * exported from the package (only the React <BorderBeam> component is), so
 * it's transcribed here from border-beam/dist/index.es.js (pulseDriver
 * internals: `pe`/`ra`/`Fe`/`ga`), parameterized for the single instance this
 * dashboard uses (id: gsci-gauge-beam, theme: dark, duration: 3.4s — see
 * frontend/scripts/generate-border-beam-css.mjs for the source of truth on
 * those numbers).
 *
 * Only the "pulse-inner" oscillator set is ported — this app never uses
 * rotate/line/pulse-outside, so that code was left out rather than carried
 * along unused.
 */
(function () {
  "use strict";

  var BEAM_ID = "gsci-gauge-beam";
  var THEME_DARK = true;
  var DURATION = 3.4; // must match generate-border-beam-css.mjs BEAM_CONFIG.duration

  function easeInOutCosine(t) {
    return (1 - Math.cos(Math.PI * 2 * t)) / 2;
  }

  // Port of border-beam's `pe(type, theme, duration)` for type === "pulse-inner".
  function pulseInnerTuning(isDark, duration) {
    var o = duration / 2.3;
    return {
      sp: 0.28,
      dr: isDark ? 33 : 40,
      op: isDark ? 0.48 : 0.45,
      gh: isDark ? 0.34 : 0.22,
      bs: (isDark ? 1.9 : 2.6) * o,
      ss: (isDark ? 2.6 : 4.6) * o,
      ghs: (isDark ? 2.4 : 5.5) * o,
    };
  }

  // Port of border-beam's `ra(id, config)`.
  function buildOscillators(id, c) {
    var sp = c.sp, dr = c.dr, op = c.op, gh = c.gh, bs = c.bs, ss = c.ss, ghs = c.ghs;
    return [
      { prop: "--bw1-" + id, a: 1 - sp, b: 1 + sp * 1.1, period: ss * 0.9, delay: 0, unit: "" },
      { prop: "--bh1-" + id, a: 1 + sp * 0.9, b: 1 - sp * 0.85, period: ss * 1.26, delay: 0, unit: "" },
      { prop: "--bx1-" + id, a: -dr, b: dr * 0.9, period: bs * 1.6, delay: 0, unit: "px" },
      { prop: "--by1-" + id, a: dr * 0.55, b: -dr * 0.7, period: bs * 1.6, delay: 0, unit: "px" },
      { prop: "--bw2-" + id, a: 1 + sp, b: 1 - sp * 0.85, period: ss * 1.1, delay: 0, unit: "" },
      { prop: "--bh2-" + id, a: 1 - sp * 0.8, b: 1 + sp * 1.05, period: ss * 0.81, delay: 0, unit: "" },
      { prop: "--bx2-" + id, a: dr * 0.8, b: -dr * 0.9, period: bs * 1.88, delay: 0, unit: "px" },
      { prop: "--by2-" + id, a: -dr, b: dr * 0.65, period: bs * 1.88, delay: 0, unit: "px" },
      { prop: "--bw3-" + id, a: 1 - sp * 0.6, b: 1 + sp * 1.15, period: ss * 0.98, delay: 0, unit: "" },
      { prop: "--bh3-" + id, a: 1 + sp * 0.75, b: 1 - sp, period: ss * 1.4, delay: 0, unit: "" },
      { prop: "--bx3-" + id, a: -dr * 0.6, b: dr, period: bs * 1.45, delay: 0, unit: "px" },
      { prop: "--by3-" + id, a: -dr * 0.85, b: dr * 0.45, period: bs * 1.45, delay: 0, unit: "px" },
      { prop: "--bgh-" + id, a: 1 - gh, b: 1 + gh, period: ghs, delay: 0, unit: "" },
      { prop: "--bop-tl-" + id, a: 1 - op, b: 1, period: dr, delay: 0, unit: "" },
      { prop: "--bop-tr-" + id, a: 1 - op, b: 1, period: dr * 1.32, delay: dr * 0.28, unit: "" },
      { prop: "--bop-bl-" + id, a: 1 - op, b: 1, period: dr * 0.84, delay: dr * 0.55, unit: "" },
      { prop: "--bop-br-" + id, a: 1 - op, b: 1, period: dr * 1.58, delay: dr * 0.83, unit: "" },
    ];
  }

  var FRAME_BUDGET_MS = 1000 / 30 - 2; // ~30fps cap, matches the source package
  var rafId = null;
  var lastFrameMs = 0;

  function tick(nowMs) {
    rafId = requestAnimationFrame(tick);
    if (nowMs - lastFrameMs < FRAME_BUDGET_MS) return;
    lastFrameMs = nowMs;
    var nowSec = nowMs / 1000;
    for (var i = 0; i < oscillators.length; i++) {
      var o = oscillators[i];
      var s = (nowSec - o.delay) / o.period;
      var value = o.a + (o.b - o.a) * easeInOutCosine(s);
      el.style.setProperty(o.prop, o.unit === "px" ? value.toFixed(2) + "px" : value.toFixed(4));
    }
  }

  function start() {
    if (rafId === null) rafId = requestAnimationFrame(tick);
  }
  function stop() {
    if (rafId !== null) {
      cancelAnimationFrame(rafId);
      rafId = null;
    }
  }

  var el = document.querySelector('[data-beam="' + BEAM_ID + '"]');
  if (!el) return;

  var reducedMotion = typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reducedMotion) return; // CSS already disables the beam's own animations; skip the JS loop too.

  var oscillators = buildOscillators(BEAM_ID, pulseInnerTuning(THEME_DARK, DURATION));

  var visible = true;
  if (typeof IntersectionObserver !== "undefined") {
    var io = new IntersectionObserver(function (entries) {
      visible = entries[0].isIntersecting;
      if (visible && document.visibilityState !== "hidden") start();
      else stop();
    });
    io.observe(el);
  }
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") stop();
    else if (visible) start();
  });

  start();
})();
