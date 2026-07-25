/**
 * Framework-free wrapper around `thinking-orbs`.
 *
 * `thinking-orbs` ships a React <ThinkingOrb> component, but its actual
 * drawing logic (`MODE_DRAWS`, `STATE_TO_MODE`, `resolvePreset`) is plain
 * canvas 2D code with zero React dependency — the README even notes the
 * package "works identically in Chrome, Safari and Firefox" on plain
 * <canvas>. We import only those three named exports; esbuild tree-shakes
 * away the unused <ThinkingOrb> component (and its `react`/`react/jsx-runtime`
 * imports) since this app has no React runtime.
 *
 * This re-implements the same mount/animate/pause lifecycle the React
 * component uses internally (see thinking-orbs/dist/index.es.js `Tt`), just
 * driven by a plain function instead of hooks.
 */
import { MODE_DRAWS, STATE_TO_MODE, resolvePreset } from "thinking-orbs";

const REDUCED_MOTION = typeof matchMedia !== "undefined"
  ? matchMedia("(prefers-reduced-motion: reduce)")
  : null;

/**
 * Mount an animated thinking-orb onto a <canvas> element.
 *
 * @param {HTMLCanvasElement} canvas
 * @param {{state?: string, size?: number, speed?: number, paused?: boolean}} opts
 * @returns {() => void} Teardown function.
 */
function mount(canvas, opts = {}) {
  const state = STATE_TO_MODE[opts.state] ? opts.state : "composing";
  const size = opts.size || 20;
  const speedMul = opts.speed || 1;

  const dpr = Math.min(2, (typeof devicePixelRatio !== "undefined" && devicePixelRatio) || 1);
  canvas.width = Math.round(size * dpr);
  canvas.height = Math.round(size * dpr);
  canvas.style.width = size + "px";
  canvas.style.height = size + "px";
  canvas.style.display = "block";

  const ctx = canvas.getContext("2d");
  if (!ctx) return () => {};

  const { mode, speed, opts: modeOpts } = resolvePreset(state, size);
  const draw = MODE_DRAWS[mode];
  const isDark = true; // dashboard is dark-theme only
  const effectiveSpeed = speed * speedMul;

  const paint = (tSeconds) => {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size, size);
    draw(ctx, size, tSeconds, isDark, modeOpts);
  };

  const reduced = !!(REDUCED_MOTION && REDUCED_MOTION.matches);
  if (reduced || opts.paused) {
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

  paint((performance.now() / 1000) * effectiveSpeed);

  let visible = true;
  const io = typeof IntersectionObserver !== "undefined"
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

  if (!io) start();

  return () => {
    stop();
    if (io) io.disconnect();
    document.removeEventListener("visibilitychange", onVisibility);
  };
}

window.ThinkingOrbs = { mount };
