/* Terminal touch and keyboard helpers (Dash loads every file in assets/). */
(function () {
  // Category details open on hover or focus. Mobile Safari does not focus a
  // button on tap, so focus it explicitly; tapping anywhere else blurs it and
  // the detail closes.
  document.addEventListener("pointerup", function (event) {
    if (event.pointerType === "mouse") return;
    var button = event.target.closest && event.target.closest(".cat-name");
    if (button) button.focus();
  });

  // Escape closes the Subscribe box (react-bootstrap root close); put focus
  // back on the Subscribe button so keyboard users keep their place.
  var subscribeWasOpen = false;
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") subscribeWasOpen = !!document.querySelector(".newsletter-popover");
  });
  document.addEventListener("keyup", function (event) {
    if (event.key !== "Escape" || !subscribeWasOpen) return;
    subscribeWasOpen = false;
    var tries = 0;
    (function refocus() {
      if (document.querySelector(".newsletter-popover")) {
        if (++tries < 10) setTimeout(refocus, 100);  // wait out the fade
        return;
      }
      var button = document.getElementById("newsletter-btn");
      if (button) button.focus();
    })();
  });
  // Phones and touch screens: a one-finger swipe over the map should scroll
  // the page, so map dragging and scroll zoom are off there.
  // Desktop keeps the server's dragmode "pan" and scrollZoom. Tapping a port
  // still shows its hover box. Re-applied after every render because each
  // refresh sends the server figure again.
  var touchMap = window.matchMedia("(max-width: 760px), (pointer: coarse)");

  function applyMapMode(gd) {
    if (!gd || !gd.layout || !gd._context || !window.Plotly) return;
    var touch = touchMap.matches;
    var mode = touch ? { dragmode: false } : { dragmode: "pan" };
    var zoom = !touch;
    if (gd.layout.dragmode === mode.dragmode && gd._context.scrollZoom === zoom) return;
    // react (not relayout) so the config change also lands: with scrollZoom
    // left on, the map still swallows wheel and trackpad scrolling.
    window.Plotly.react(gd, gd.data, Object.assign({}, gd.layout, mode),
                        Object.assign({}, gd._context, { scrollZoom: zoom }));
  }

  function bindMap() {
    var gd = document.querySelector("#world-map .js-plotly-plot");
    if (!gd || typeof gd.on !== "function" || gd.__gsciMapBound) return;
    gd.__gsciMapBound = true;
    gd.on("plotly_afterplot", function () { applyMapMode(gd); });
    applyMapMode(gd);
  }

  new MutationObserver(bindMap).observe(document.documentElement, { childList: true, subtree: true });
  var onChange = function () { applyMapMode(document.querySelector("#world-map .js-plotly-plot")); };
  if (touchMap.addEventListener) touchMap.addEventListener("change", onChange);
  else if (touchMap.addListener) touchMap.addListener(onChange);
  window.addEventListener("resize", onChange);  // rotation and window resizes
})();
