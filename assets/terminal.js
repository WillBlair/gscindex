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
})();
