import { describe, expect, it } from "vitest";

import type { SeriesPoint } from "../src/api/types";
import { componentKeys, formatYears, toChartRows } from "../src/lib/series";

const point = (overrides: Partial<SeriesPoint> = {}): SeriesPoint => ({
  week_start: "2026-06-01",
  chronological_age: 36.2,
  composite_age: 33.8,
  ci_low: 28.1,
  ci_high: 39.5,
  is_low_confidence: false,
  components: [
    { component: "kdm", age_years: 34.0, sigma_years: 6.5, inputs: {} },
    { component: "hrv_norm", age_years: 32.0, sigma_years: 7.0, inputs: {} },
  ],
  ...overrides,
});

describe("toChartRows", () => {
  it("returns an empty array for no points", () => {
    expect(toChartRows([])).toEqual([]);
  });

  it("maps the composite and chronological ages", () => {
    const [row] = toChartRows([point()]);
    expect(row.bioAge).toBeCloseTo(33.8);
    expect(row.chronoAge).toBeCloseTo(36.2);
    expect(row.week).toBe("2026-06-01");
  });

  it("expresses the band as [low, high] for an area chart", () => {
    const [row] = toChartRows([point()]);
    expect(row.band).toEqual([28.1, 39.5]);
  });

  it("carries the low-confidence flag through", () => {
    const [row] = toChartRows([point({ is_low_confidence: true })]);
    expect(row.lowConfidence).toBe(true);
  });

  it("flattens component ages into keyed fields", () => {
    const [row] = toChartRows([point()]);
    expect(row.componentAges.kdm).toBeCloseTo(34.0);
    expect(row.componentAges.hrv_norm).toBeCloseTo(32.0);
  });

  it("flattens component sigmas into keyed fields alongside their ages", () => {
    const [row] = toChartRows([point()]);
    expect(row.componentSigmas.kdm).toBeCloseTo(6.5);
    expect(row.componentSigmas.hrv_norm).toBeCloseTo(7.0);
  });

  it("tolerates a point with no components when flattening sigmas", () => {
    const [row] = toChartRows([point({ components: [] })]);
    expect(row.componentSigmas).toEqual({});
  });

  it("preserves input order", () => {
    const rows = toChartRows([
      point({ week_start: "2026-06-01" }),
      point({ week_start: "2026-06-08" }),
    ]);
    expect(rows.map((r) => r.week)).toEqual(["2026-06-01", "2026-06-08"]);
  });

  it("tolerates a point with no components", () => {
    const [row] = toChartRows([point({ components: [] })]);
    expect(row.componentAges).toEqual({});
  });

  it("fills a gap in the middle with a null row per missing ISO week", () => {
    // Three weeks apart (two missing weeks in between: 06-08 and 06-15) so the band
    // has more than one gap week to prove every one is emitted, not just the first.
    const rows = toChartRows([
      point({ week_start: "2026-06-01" }),
      point({ week_start: "2026-06-22" }),
    ]);
    expect(rows.map((r) => r.week)).toEqual([
      "2026-06-01",
      "2026-06-08",
      "2026-06-15",
      "2026-06-22",
    ]);
    const [scored1, gap1, gap2, scored2] = rows;
    expect(scored1.bioAge).not.toBeNull();
    expect(scored2.bioAge).not.toBeNull();
    expect(gap1.bioAge).toBeNull();
    expect(gap1.chronoAge).toBeNull();
    expect(gap1.ciLow).toBeNull();
    expect(gap1.ciHigh).toBeNull();
    expect(gap1.band).toBeNull();
    expect(gap1.lowConfidence).toBe(false);
    expect(gap1.componentAges).toEqual({});
    expect(gap1.componentSigmas).toEqual({});
    expect(gap2.bioAge).toBeNull();
  });

  it("returns one row per week across the full span, not one row per scored week", () => {
    const rows = toChartRows([
      point({ week_start: "2026-06-01" }),
      point({ week_start: "2026-07-06" }), // five weeks later
    ]);
    // 2026-06-01 to 2026-07-06 inclusive, stepping by 7 days, is 6 rows -- far more
    // than the 2 SeriesPoints actually scored.
    expect(rows).toHaveLength(6);
    expect(rows.filter((r) => r.bioAge !== null)).toHaveLength(2);
  });

  it("returns a single row when only one week is scored", () => {
    const rows = toChartRows([point({ week_start: "2026-06-01" })]);
    expect(rows).toHaveLength(1);
    expect(rows[0].week).toBe("2026-06-01");
  });
});

describe("componentKeys", () => {
  it("returns the union of component names across all points", () => {
    const keys = componentKeys([
      point({ components: [{ component: "kdm", age_years: 1, sigma_years: 1, inputs: {} }] }),
      point({ components: [{ component: "ntnu_fitness", age_years: 1, sigma_years: 1, inputs: {} }] }),
    ]);
    expect(keys.sort()).toEqual(["kdm", "ntnu_fitness"]);
  });

  it("deduplicates", () => {
    expect(componentKeys([point(), point()]).sort()).toEqual(["hrv_norm", "kdm"]);
  });
});

describe("formatYears", () => {
  it("shows one decimal place", () => {
    expect(formatYears(33.847)).toBe("33.8 yr");
  });

  it("renders a dash for null", () => {
    expect(formatYears(null)).toBe("—");
  });

  it("renders a dash for undefined", () => {
    expect(formatYears(undefined)).toBe("—");
  });
});
