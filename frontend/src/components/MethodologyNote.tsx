export function MethodologyNote() {
  return (
    <aside className="methodology-note">
      <strong>How to read this.</strong> This is a fitness and autonomic proxy, not a
      validated aging clock. Absolute values carry error bars of several years — the
      shaded band is a 95% interval — and the <em>trend</em> is far more reliable than any
      single point. Hollow markers mark weeks with thin data coverage. Toggled component
      lines show a point estimate only, each with its own (often wider) uncertainty —
      hover a point to see that component's interval. See{" "}
      <code>docs/METHODOLOGY.md</code> for every equation, constant and caveat.
    </aside>
  );
}
