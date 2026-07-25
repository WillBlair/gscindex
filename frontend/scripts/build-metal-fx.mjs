import { build } from "esbuild";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const outfile = path.resolve(__dirname, "../../assets/vendor/metal-fx.min.js");

await build({
  entryPoints: [path.resolve(__dirname, "../src/metal-fx-entry.js")],
  bundle: true,
  minify: true,
  format: "iife",
  target: "es2019",
  treeShaking: true,
  outfile,
  // metal-fx's only React dependency is its unused <MetalFx> export; see
  // build-thinking-orbs.mjs for why this alias is needed.
  alias: {
    react: path.resolve(__dirname, "shims/react.mjs"),
    "react/jsx-runtime": path.resolve(__dirname, "shims/react-jsx-runtime.mjs"),
  },
  banner: {
    js: "/* metal-fx (MIT, © Jakub Antalik) — vendored non-React WebGL ring logic. See frontend/src/metal-fx-entry.js. */",
  },
  logLevel: "info",
});
