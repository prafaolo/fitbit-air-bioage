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
});
