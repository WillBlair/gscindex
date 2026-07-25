/**
 * Wires vendored effects into restrained mount points.
 *
 * Placement:
 *   - thinking-orbs: once — header brand mark only (`.brand-orb`)
 *   - border-beam (pulse): hero gauge + map panels (CSS/driver; data-beam attrs)
 *   - metal-fx: small accent beside the industry profile select
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
        state: canvas.getAttribute("data-orb-state") || "listening",
        size: parseInt(canvas.getAttribute("data-orb-size"), 10) || 34,
      });
    }
  }

  function mountMetal(root) {
    if (!window.MetalFx) return;
    var badges = root.querySelectorAll(
      ".profile-metal-badge:not([data-metal-mounted]), .brand-metal-badge:not([data-metal-mounted])"
    );
    for (var i = 0; i < badges.length; i++) {
      var badge = badges[i];
      badge.setAttribute("data-metal-mounted", "");
      window.MetalFx.mount(badge, {
        preset: badge.getAttribute("data-metal-preset") || "silver",
        size: parseInt(badge.getAttribute("data-metal-size"), 10) || 18,
        strength: 0.75,
      });
    }
  }

  function scan(root) {
    mountOrbs(root);
    mountMetal(root);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      scan(document);
    });
  } else {
    scan(document);
  }

  if (typeof MutationObserver !== "undefined") {
    var observer = new MutationObserver(function () {
      scan(document);
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });
  }
})();
