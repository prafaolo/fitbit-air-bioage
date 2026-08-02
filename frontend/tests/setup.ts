/**
 * jsdom has no ResizeObserver — Recharts' <ResponsiveContainer> reads it on
 * mount to size the SVG. This is a minimal no-op polyfill so chart tests can
 * render without an environment-specific crash; it does not need to fire
 * callbacks since the tests only assert on DOM structure, not on resize
 * behavior.
 */
class ResizeObserverPolyfill {
  observe() {}
  unobserve() {}
  disconnect() {}
}

if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = ResizeObserverPolyfill as unknown as typeof ResizeObserver;
}

/**
 * jsdom never lays out elements, so every element's getBoundingClientRect is
 * 0x0. Recharts' <ResponsiveContainer> reads that rect on mount to size its
 * SVG and renders nothing (not even axis labels) at zero size. Stubbing a
 * fixed, non-zero rect lets the chart render its real content in tests.
 */
Element.prototype.getBoundingClientRect = () =>
  ({
    width: 800,
    height: 420,
    top: 0,
    left: 0,
    bottom: 420,
    right: 800,
    x: 0,
    y: 0,
    toJSON() {},
  }) as DOMRect;
