import { build } from "esbuild";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const outfile = path.resolve(__dirname, "../../assets/vendor/thinking-orbs.min.js");

await build({
  entryPoints: [path.resolve(__dirname, "../src/thinking-orbs-entry.js")],
  bundle: true,
  minify: true,
  format: "iife",
  target: "es2019",
  treeShaking: true,
  outfile,
  // thinking-orbs' only React dependency is its unused <ThinkingOrb> export;
  // aliasing react(/jsx-runtime) to trivial ESM stubs lets esbuild prove that
  // code path is dead and drop real React from the bundle entirely.
  alias: {
    react: path.resolve(__dirname, "shims/react.mjs"),
    "react/jsx-runtime": path.resolve(__dirname, "shims/react-jsx-runtime.mjs"),
  },
  banner: {
    js: "/* thinking-orbs (MIT, © Jakub Antalik) — vendored non-React canvas draw logic. See frontend/src/thinking-orbs-entry.js. */",
  },
  logLevel: "info",
});
