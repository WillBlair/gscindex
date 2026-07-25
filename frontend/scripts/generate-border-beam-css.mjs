/**
 * border-beam ships a React component whose CSS-generation internals
 * (`styles.ts`) are NOT exported — only `<BorderBeam>` itself is public. To
 * get the *exact* CSS the real package would emit for our chosen config
 * (pulse-inner, mono palette, dark theme) without hand-transcribing its
 * gradient math, we server-render the actual component with
 * `react-dom/server` and lift the `<style>` tag it produces.
 *
 * react/react-dom here are build-time-only devDependencies used purely as a
 * code-generation harness — nothing React ships to the browser. The output
 * of this script (assets/vendor/border-beam-pulse.css) is a committed,
 * static artifact; Dash serves it like any other assets/ file.
 *
 * The animated custom-property "breathing" driver (which border-beam runs
 * via a plain, non-React requestAnimationFrame loop internally) is ported by
 * hand in assets/vendor/border-beam-pulse-driver.js — see that file for the
 * algorithm and its source attribution.
 */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { BorderBeam } from "border-beam";
import { fileURLToPath } from "node:url";
import path from "node:path";
import fs from "node:fs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const outfile = path.resolve(__dirname, "../../assets/vendor/border-beam-pulse.css");

// This is the single beam instance used across the whole dashboard (the hero
// gauge panel) — see components/layout.py for `data-beam="gsci-gauge-beam"`.
export const BEAM_ID = "gsci-gauge-beam";
export const BEAM_CONFIG = {
  size: "pulse-inner",
  colorVariant: "mono", // grayscale only — no rainbow/indigo chrome per design tokens
  theme: "dark",
  duration: 3.4, // slow breathe, ~2x the package default (2.3s) — "quiet" per design brief
  strength: 0.55, // subdued; a hint of life, not a light show
  borderRadius: 10, // matches --radius-panel in assets/style.css (panel corner radius)
};

const markup = renderToStaticMarkup(
  React.createElement(
    BorderBeam,
    { ...BEAM_CONFIG, active: true },
    React.createElement("div", { style: { borderRadius: 10 } })
  )
);

const styleMatch = markup.match(/<style>([\s\S]*?)<\/style>/);
if (!styleMatch) {
  throw new Error("generate-border-beam-css: could not find generated <style> in SSR markup");
}
// React SSR always HTML-escapes text children (it has no idea this text is
// going into a <style> tag specifically) — undo that before writing real CSS.
function unescapeHtml(s) {
  return s
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");
}
let css = unescapeHtml(styleMatch[1]);

// React's SSR useId() produces something like ":r0:" (sanitized to "«r0»" or
// similar depending on version) for the first — and here, only — component
// instance in the tree. Replace whatever token it minted with our stable,
// human-readable id so components/layout.py and the pulse driver can target
// it deterministically regardless of React internals/version drift.
const idMatch = markup.match(/data-beam="([^"]+)"/);
if (!idMatch) {
  throw new Error("generate-border-beam-css: could not find data-beam id in SSR markup");
}
const generatedId = idMatch[1];
css = css.split(generatedId).join(BEAM_ID);

const header = `/* GENERATED FILE — do not hand-edit.
 * Produced by frontend/scripts/generate-border-beam-css.mjs from the real
 * "border-beam" npm package (MIT, (c) Jakub Antalik), config:
 * ${JSON.stringify(BEAM_CONFIG)}
 * Regenerate with: cd frontend && npm run build
 */\n`;

fs.writeFileSync(outfile, header + css.trim() + "\n");
console.log(`Wrote ${outfile} (${(header.length + css.length)} bytes), beam id = ${BEAM_ID}`);
