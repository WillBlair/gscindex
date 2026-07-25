// Build-time-only stub for the `react` package.
//
// thinking-orbs / metal-fx each have exactly one entry point that needs React
// (their <ThinkingOrb>/<MetalFx> components); we never import those exports
// from our vanilla entry files, so this module's bindings are dead code by
// the time esbuild's tree shaker runs. The real `react` package ships
// `react/jsx-runtime` and `react` as CommonJS with a `process.env.NODE_ENV`
// branch, which esbuild cannot tree-shake through — aliasing to this trivial
// ESM stub lets the actual bundler eliminate the unused React component
// entirely instead of pulling in ~40KB of React runtime we never execute.
export function useState() { throw new Error("react stub: unreachable in vendored build"); }
export function useEffect() { throw new Error("react stub: unreachable in vendored build"); }
export function useRef() { throw new Error("react stub: unreachable in vendored build"); }
export function useMemo() { throw new Error("react stub: unreachable in vendored build"); }
export function useLayoutEffect() { throw new Error("react stub: unreachable in vendored build"); }
export function useImperativeHandle() { throw new Error("react stub: unreachable in vendored build"); }
export function useId() { throw new Error("react stub: unreachable in vendored build"); }
export function useCallback() { throw new Error("react stub: unreachable in vendored build"); }
export function forwardRef(render) { return render; }
export default {};
