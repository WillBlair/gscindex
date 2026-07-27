// Build-time-only stub for `react/jsx-runtime`. See react.mjs shim for why
// this exists — it lets esbuild tree-shake the unused React component out of
// thinking-orbs / metal-fx instead of bundling real React.
export function jsx() { throw new Error("react/jsx-runtime stub: unreachable in vendored build"); }
export function jsxs() { throw new Error("react/jsx-runtime stub: unreachable in vendored build"); }
export const Fragment = Symbol("Fragment");
