/**
 * Wires vendored effects into restrained mount points.
 * Filename zzz-* so Dash loads this AFTER thinking-orbs.min.js / metal-fx.min.js.
 *
 * Placement:
 *   - thinking-orbs: once — header brand mark
 *     (React equiv: <ThinkingOrb state="working" size={64} />)
 */
(function () {
  "use strict";

  function mountOrbs(root) {
    if (!window.ThinkingOrbs) return false;
    var canvases = root.querySelectorAll(
      "canvas.thinking-orb-mount:not([data-orb-mounted])"
    );
    for (var i = 0; i < canvases.length; i++) {
      var canvas = canvases[i];
      canvas.setAttribute("data-orb-mounted", "");
      window.ThinkingOrbs.mount(canvas, {
        // React: <ThinkingOrb state="working" size={64} theme="dark" />
        state: canvas.getAttribute("data-orb-state") || "working",
        size: parseInt(canvas.getAttribute("data-orb-size"), 10) || 64,
        theme: "dark",
        forceMotion:
          canvas.getAttribute("data-orb-force-motion") === "true" ||
          canvas.classList.contains("brand-orb"),
      });
    }
    return true;
  }

  function scan(root) {
    mountOrbs(root);
  }

  function boot() {
    scan(document);
    // Retry briefly if vendor bundle hasn't attached yet
    if (!window.ThinkingOrbs) {
      var tries = 0;
      var timer = setInterval(function () {
        tries += 1;
        if (mountOrbs(document) || tries >= 20) clearInterval(timer);
      }, 50);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  if (typeof MutationObserver !== "undefined") {
    var observer = new MutationObserver(function () {
      scan(document);
    });
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
    });
  }
})();
