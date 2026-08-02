import type { SeriesPoint } from "../api/types";

export interface ChartRow {
  week: string;
  /**
   * `null` marks an ISO week that exists in the full span but was never
   * scored (rescore_all only writes weeks that clear the coverage gate). A
   * default Recharts axis is a category scale keyed on `week`, so an absent
   * week would otherwise just not appear — the line would connect straight
   * across the gap with equal spacing and no visual break, misrepresenting
   * elapsed time. Emitting an explicit null row lets Recharts break the line
   * there instead (see toChartRows and connectNulls default).
   */
  bioAge: number | null;
  chronoAge: number | null;
  ciLow: number | null;
  ciHigh: number | null;
  /** Recharts renders a shaded band from a [low, high] tuple; null for an unscored week. */
  band: [number, number] | null;
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

/** Add `days` (may be negative) to an ISO date string, in UTC so the result never
 * shifts by a day depending on the caller's local timezone. */
function addDaysIso(iso: string, days: number): string {
  const [year, month, day] = iso.split("-").map(Number);
  const shifted = new Date(Date.UTC(year, month - 1, day) + days * 86_400_000);
  return shifted.toISOString().slice(0, 10);
}

/** Every ISO week start (7-day step) from `first` through `last`, inclusive of both. */
function weeksBetween(first: string, last: string): string[] {
  const weeks: string[] = [];
  for (let week = first; week <= last; week = addDaysIso(week, 7)) {
    weeks.push(week);
  }
  return weeks;
}

export function toChartRows(points: SeriesPoint[]): ChartRow[] {
  if (points.length === 0) return [];

  const byWeek = new Map(points.map((point) => [point.week_start, point]));
  const fullSpan = weeksBetween(points[0].week_start, points[points.length - 1].week_start);

  return fullSpan.map((week) => {
    const point = byWeek.get(week);
    if (!point) {
      return {
        week,
        bioAge: null,
        chronoAge: null,
        ciLow: null,
        ciHigh: null,
        band: null,
        lowConfidence: false,
        componentAges: {},
        componentSigmas: {},
      };
    }
    return {
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
    };
  });
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
