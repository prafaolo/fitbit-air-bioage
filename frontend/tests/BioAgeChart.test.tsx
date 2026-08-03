import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BioAgeChart } from "../src/components/BioAgeChart";
import type { SeriesPoint } from "../src/api/types";

const points: SeriesPoint[] = [
  {
    week_start: "2026-06-01",
    chronological_age: 36.2,
    composite_age: 33.8,
    ci_low: 28.1,
    ci_high: 39.5,
    is_low_confidence: false,
    components: [{ component: "kdm", age_years: 34.0, sigma_years: 6.5, inputs: {} }],
  },
  {
    week_start: "2026-06-08",
    chronological_age: 36.2,
    composite_age: 33.1,
    ci_low: 27.5,
    ci_high: 38.7,
    is_low_confidence: true,
    components: [{ component: "kdm", age_years: 33.5, sigma_years: 6.5, inputs: {} }],
  },
];

describe("BioAgeChart", () => {
  it("renders an empty state when there are no points", () => {
    render(<BioAgeChart points={[]} visibleComponents={[]} />);
    expect(screen.getByText(/no biological age data yet/i)).toBeDefined();
  });

  it("renders a chart region when points exist", () => {
    const { container } = render(
      <BioAgeChart points={points} visibleComponents={[]} />,
    );
    expect(container.querySelector(".recharts-responsive-container")).not.toBeNull();
  });

  it("labels the y axis in years", () => {
    render(<BioAgeChart points={points} visibleComponents={[]} />);
    expect(screen.getByText(/age \(years\)/i)).toBeDefined();
  });

  it("does not crash when a component series is toggled on", () => {
    const { container } = render(
      <BioAgeChart points={points} visibleComponents={["kdm"]} />,
    );
    expect(container.querySelector(".recharts-responsive-container")).not.toBeNull();
  });

  // The four tests above only prove the chart *region* exists, the y-axis
  // label renders, and nothing throws — none of them prove a single series
  // actually drew a mark. Recharts renders real SVG in jsdom (confirmed by
  // dumping container.innerHTML during development — <path>/<circle>
  // elements with the same name/stroke/fill/dataKey props passed to
  // <Line>/<Area>/<Scatter>), so these query that SVG directly rather than
  // asserting only on chrome that would still be present if every series
  // silently failed to render.

  it("renders the biological age line, the dashed chronological reference, and the confidence band", () => {
    const { container } = render(
      <BioAgeChart points={points} visibleComponents={[]} />,
    );
    expect(container.querySelector('path[name="Biological age"]')).not.toBeNull();
    const chronoLine = container.querySelector('path[name="Chronological age"]');
    expect(chronoLine).not.toBeNull();
    expect(chronoLine?.getAttribute("stroke-dasharray")).toBe("6 4");
    const band = container.querySelector('path[name="95% interval"]');
    expect(band).not.toBeNull();
    expect(band?.getAttribute("fill-opacity")).toBe("0.1");
  });

  it("renders the low-confidence week's marker hollow, not filled", () => {
    const { container } = render(
      <BioAgeChart points={points} visibleComponents={[]} />,
    );
    // Only the second fixture point has is_low_confidence: true, so exactly
    // one marker should exist — the low-confidence Scatter series has no
    // value (undefined) for the first row, so Recharts draws nothing there.
    const markers = container.querySelectorAll('path[name="Low data coverage"]');
    expect(markers).toHaveLength(1);
    const [marker] = markers;
    // Hollow means the fill matches the dark chart surface (so the marker
    // reads as an outline), not the accent color used for its stroke —
    // the brief's own placeholder code used fill="#ffffff", which would
    // have rendered a solid white dot on this dark surface instead.
    expect(marker.getAttribute("fill")).toBe("#1a1a19");
    expect(marker.getAttribute("stroke")).toBe("#3987e5");
    expect(marker.getAttribute("fill")).not.toBe(marker.getAttribute("stroke"));
  });

  it("renders a line for a toggled-on component, and none when no components are visible", () => {
    const { container: withKdm } = render(
      <BioAgeChart points={points} visibleComponents={["kdm"]} />,
    );
    expect(withKdm.querySelector('path[name="KDM"]')).not.toBeNull();

    const { container: withoutKdm } = render(
      <BioAgeChart points={points} visibleComponents={[]} />,
    );
    expect(withoutKdm.querySelector('path[name="KDM"]')).toBeNull();
  });
});
