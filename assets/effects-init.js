/**
 * Wires the three vendored effect packages (thinking-orbs, border-beam,
 * metal-fx — see assets/vendor/ and frontend/) into specific, restrained
 * spots in the live dashboard. Dash re-renders parts of the DOM (skeleton →
 * live layout, briefing regeneration, etc.), so this uses a MutationObserver
 * instead of a one-shot DOMContentLoaded scan.
 *
 * Placement (see docs/superpowers/specs/2026-07-25-ui-makeover-design.md for
 * the "quiet, no constant decoration" brief this respects):
 *   - thinking-orbs: cold-start loading overlay + AI briefing generation —
 *     both genuine "the system is thinking" states, never idle decoration.
 *   - border-beam (pulse): hero gauge panel only, via CSS + border-beam-
 *     pulse-driver.js (data-beam attribute is set server-side in
 *     components/layout.py; nothing to mount here).
 *   - metal-fx: a single small circular brand badge in the header.
 */
(function () {
  "use strict";

  function mountOrbs(root) {
    if (!window.ThinkingOrbs) return;
    var canvases = root.querySelectorAll("canvas.thinking-orb-mount:not([data-orb-mounted])");
    for (var i = 0; i < canvases.length; i++) {
      var canvas = canvases[i];
      canvas.setAttribute("data-orb-mounted", "");
      window.ThinkingOrbs.mount(canvas, {
        state: canvas.getAttribute("data-orb-state") || "composing",
        size: parseInt(canvas.getAttribute("data-orb-size"), 10) || 20,
      });
    }
  }

  function mountMetal(root) {
    if (!window.MetalFx) return;
    var badges = root.querySelectorAll(".brand-metal-badge:not([data-metal-mounted])");
    for (var i = 0; i < badges.length; i++) {
      var badge = badges[i];
      badge.setAttribute("data-metal-mounted", "");
      window.MetalFx.mount(badge, {
        preset: badge.getAttribute("data-metal-preset") || "silver",
        size: parseInt(badge.getAttribute("data-metal-size"), 10) || 28,
        strength: 0.8,
      });
    }
  }

  function scan(root) {
    mountOrbs(root);
    mountMetal(root);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { scan(document); });
  } else {
    scan(document);
  }

  if (typeof MutationObserver !== "undefined") {
    var observer = new MutationObserver(function () { scan(document); });
    observer.observe(document.documentElement, { childList: true, subtree: true });
  }
})();
