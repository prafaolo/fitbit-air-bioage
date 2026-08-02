import type { SeriesPoint } from "../api/types";

export interface ChartRow {
  week: string;
  bioAge: number;
  chronoAge: number;
  ciLow: number;
  ciHigh: number;
  /** Recharts renders a shaded band from a [low, high] tuple. */
  band: [number, number];
  lowConfidence: boolean;
  componentAges: Record<string, number>;
  /**
   * Each component's own sigma_years, mirroring componentAges. No estimate is
   * rendered without an accompanying uncertainty (see
   * backend/src/bioage/estimators/models.py) — the composite gets a drawn
   * band; components carry their sigma through here so the chart can surface
   * an interval (age ± 1.96·sigma) on hover instead of showing four more
   * shaded bands, which would make the chart unreadable.
   */
  componentSigmas: Record<string, number>;
}

export function toChartRows(points: SeriesPoint[]): ChartRow[] {
  return points.map((point) => ({
    week: point.week_start,
    bioAge: point.composite_age,
    chronoAge: point.chronological_age,
    ciLow: point.ci_low,
    ciHigh: point.ci_high,
    band: [point.ci_low, point.ci_high],
    lowConfidence: point.is_low_confidence,
    componentAges: Object.fromEntries(
      point.components.map((c) => [c.component, c.age_years]),
    ),
    componentSigmas: Object.fromEntries(
      point.components.map((c) => [c.component, c.sigma_years]),
    ),
  }));
}

export function componentKeys(points: SeriesPoint[]): string[] {
  const keys = new Set<string>();
  for (const point of points) {
    for (const component of point.components) keys.add(component.component);
  }
  return [...keys];
}

export function formatYears(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value.toFixed(1)} yr`;
}
