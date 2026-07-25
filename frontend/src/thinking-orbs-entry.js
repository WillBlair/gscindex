/**
 * Framework-free wrapper around `thinking-orbs`.
 *
 * Same draw/preset pipeline as <ThinkingOrb /> from the npm package.
 * React API equivalent:
 *   <ThinkingOrb state="working" size={64} theme="dark" />
 */
import { MODE_DRAWS, STATE_TO_MODE, resolvePreset } from "thinking-orbs";

const REDUCED_MOTION =
  typeof matchMedia !== "undefined"
    ? matchMedia("(prefers-reduced-motion: reduce)")
    : null;

/**
 * Mount an animated thinking-orb onto a <canvas> element.
 *
 * @param {HTMLCanvasElement} canvas
 * @param {{
 *   state?: string,
 *   size?: 20 | 64,
 *   speed?: number,
 *   paused?: boolean,
 *   theme?: 'dark' | 'light',
 *   forceMotion?: boolean,
 * }} opts
 * @returns {() => void} Teardown function.
 */
function mount(canvas, opts = {}) {
  const state = STATE_TO_MODE[opts.state] ? opts.state : "working";
  // Package presets are tuned ONLY for 20 and 64 — snap to nearest.
  const size = Number(opts.size) >= 42 ? 64 : 20;
  const speedMul = opts.speed || 1;
  const isDark = opts.theme !== "light"; // dashboard is dark
  // Brand mark should match the live demo even when OS "Reduce motion" is on.
  const forceMotion =
    opts.forceMotion === true ||
    canvas.getAttribute("data-orb-force-motion") === "true" ||
    canvas.classList.contains("brand-orb");

  const dpr = Math.min(
    2,
    (typeof devicePixelRatio !== "undefined" && devicePixelRatio) || 1
  );
  canvas.width = Math.round(size * dpr);
  canvas.height = Math.round(size * dpr);
  canvas.style.width = size + "px";
  canvas.style.height = size + "px";
  canvas.style.display = "block";
  canvas.setAttribute("role", "img");
  if (!canvas.getAttribute("aria-label")) {
    canvas.setAttribute("aria-label", "Thinking orb");
  }

  const ctx = canvas.getContext("2d");
  if (!ctx) return () => {};

  const { mode, speed, opts: modeOpts } = resolvePreset(state, size);
  const draw = MODE_DRAWS[mode];
  if (typeof draw !== "function") return () => {};
  const effectiveSpeed = speed * speedMul;

  const paint = (tSeconds) => {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size, size);
    draw(ctx, size, tSeconds, isDark, modeOpts);
  };

  const reduced = !!(REDUCED_MOTION && REDUCED_MOTION.matches);
  if ((reduced && !forceMotion) || opts.paused) {
    paint(0.6);
    return () => {};
  }

  let rafId = 0;
  let running = false;
  const tick = () => {
    paint((performance.now() / 1000) * effectiveSpeed);
    if (running) rafId = requestAnimationFrame(tick);
  };
  const start = () => {
    if (!running) {
      running = true;
      rafId = requestAnimationFrame(tick);
    }
  };
  const stop = () => {
    running = false;
    cancelAnimationFrame(rafId);
  };

  // Paint first frame, then start RAF immediately (don't wait on IO).
  paint((performance.now() / 1000) * effectiveSpeed);
  start();

  let visible = true;
  const io =
    typeof IntersectionObserver !== "undefined"
      ? new IntersectionObserver(([entry]) => {
          visible = entry.isIntersecting;
          if (visible && document.visibilityState !== "hidden") start();
          else stop();
        })
      : null;
  if (io) io.observe(canvas);

  const onVisibility = () => {
    if (document.visibilityState === "hidden") stop();
    else if (visible) start();
  };
  document.addEventListener("visibilitychange", onVisibility);

  return () => {
    stop();
    if (io) io.disconnect();
    document.removeEventListener("visibilitychange", onVisibility);
  };
}

window.ThinkingOrbs = { mount };
