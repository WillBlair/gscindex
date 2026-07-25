/**
 * Framework-free wrapper around `metal-fx`.
 *
 * `metal-fx` ships a React <MetalFx> component, but the WebGL shader + shared
 * render loop live in plain exported functions with no React dependency:
 * `createInstance`, `updateInstance`, `destroyInstance`, `setSharedPreset`,
 * `PRESETS`. Importing only those lets esbuild tree-shake away <MetalFx>
 * (and the `react`/`react/jsx-runtime` imports it pulls in) entirely.
 *
 * This hand-builds the same DOM shape the React component renders
 * (`.metal-fx-root` > canvas.metal-fx-canvas + div.metal-fx-inner), which is
 * enough for `createInstance` to paint the metal ring — the CSS for those
 * classes is injected automatically as a side effect of importing the
 * package (see metal-fx/dist: `eo()` runs at module load).
 *
 * The optional "reflection on neighbouring elements" feature is intentionally
 * not ported — this app uses a single, static badge, not an interactive
 * button row, so the extra DOM/observer machinery isn't worth the bytes.
 */
import { createInstance, destroyInstance, updateInstance, setSharedPreset, PRESETS } from "metal-fx";

/**
 * Mount a restrained metal ring onto a host element (sized square/circle).
 *
 * @param {HTMLElement} hostEl - Empty element; canvas + inner layers are appended to it.
 * @param {{preset?: 'silver'|'gold'|'chromatic', size?: number, strength?: number, paused?: boolean}} opts
 * @returns {() => void} Teardown function.
 */
function mount(hostEl, opts = {}) {
  const preset = PRESETS[opts.preset] ? opts.preset : "silver";
  const theme = "dark";
  const strength = typeof opts.strength === "number" ? Math.max(0, Math.min(1, opts.strength)) : 1;
  const size = opts.size || 28;
  const cornerRadius = size / 2;

  setSharedPreset(preset, theme);

  hostEl.classList.add("metal-fx-root");
  hostEl.setAttribute("data-variant", "circle");
  hostEl.setAttribute("data-shape", "circle");
  hostEl.setAttribute("data-theme", theme);
  hostEl.setAttribute("data-normalize", "false");
  hostEl.style.setProperty("--mfx-strength", String(strength));
  hostEl.style.setProperty("--mfx-radius", `${cornerRadius}px`);
  hostEl.style.width = `${size}px`;
  hostEl.style.height = `${size}px`;
  hostEl.style.borderRadius = `${cornerRadius}px`;
  hostEl.style.opacity = "0";
  hostEl.style.transition = "opacity 0.2s ease-out";

  const canvas = document.createElement("canvas");
  canvas.className = "metal-fx-canvas";
  Object.assign(canvas.style, {
    position: "absolute", inset: "0", width: "100%", height: "100%",
    display: "block", zIndex: "0", pointerEvents: "none", borderRadius: "inherit",
  });
  hostEl.appendChild(canvas);

  const inner = document.createElement("div");
  inner.className = "metal-fx-inner";
  inner.setAttribute("aria-hidden", "true");
  Object.assign(inner.style, {
    position: "absolute", inset: "0", borderRadius: "inherit", zIndex: "1", pointerEvents: "none",
  });
  hostEl.appendChild(inner);

  const instance = createInstance({
    hostCanvas: canvas,
    cssWidth: size,
    cssHeight: size,
    cornerRadius,
    kind: "circle",
    paused: !!opts.paused,
    opacityMul: strength,
    onFirstCopy: () => {
      hostEl.style.opacity = "1";
    },
  });

  let visible = true;
  const io = typeof IntersectionObserver !== "undefined"
    ? new IntersectionObserver(([entry]) => {
        visible = entry.isIntersecting;
        updateInstance(instance, { paused: !visible });
      }, { rootMargin: "64px" })
    : null;
  if (io) io.observe(hostEl);

  return () => {
    if (io) io.disconnect();
    destroyInstance(instance);
    hostEl.innerHTML = "";
  };
}

window.MetalFx = { mount };
