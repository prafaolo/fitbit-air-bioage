import type { ReactNode } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TooltipProps } from "recharts";

import type { SeriesPoint } from "../api/types";
import { formatYears, toChartRows } from "../lib/series";

/**
 * Palette sourced from the dataviz skill's validated dark-mode categorical
 * theme (references/palette.md), run through scripts/validate_palette.js
 * against the dark chart surface (#1a1a19):
 *
 *   node scripts/validate_palette.js \
 *     "#3987e5,#d95926,#199e70,#c98500,#d55181" --mode dark --surface "#1a1a19"
 *   -> ALL CHECKS PASS (lightness band, chroma floor, CVD ΔE 8.4, normal-vision
 *      ΔE 19.3, contrast >= 3:1)
 *
 * Biological age is the emphasis series and owns slot 1 (blue) on its own —
 * components are context that becomes identity-relevant only once toggled on,
 * so they take slots 2-5 in a fixed order that never changes with which are
 * visible ("color follows the entity, never its rank").
 */
const CHART_ACCENT = "#3987e5"; // slot 1 (blue) — biological age, band, low-confidence ring
const CHART_MUTED = "#898781"; // muted ink — axis ticks
const CHART_GRIDLINE = "#2c2c2a"; // one-step-off-surface — hairline gridlines
const CHART_BASELINE = "#383835"; // axis/baseline rule
const CHART_SURFACE = "#1a1a19"; // dark chart surface — fills the hollow marker
// Primary ink (#ffffff) and secondary ink (#c3c2b7) for legend/tooltip text
// live in styles.css (.chart-legend, .chart-tooltip) — text tokens, not SVG
// stroke/fill, so they belong with the rest of the app's CSS custom properties.

const COMPONENT_COLORS: Record<string, string> = {
  ntnu_fitness: "#d95926", // slot 2 (orange)
  hrv_norm: "#199e70", // slot 3 (aqua)
  steps_mortality: "#c98500", // slot 4 (yellow)
  kdm: "#d55181", // slot 5 (magenta)
};

/**
 * Secondary encoding for the component lines, on top of hue. The validator
 * passed the categorical set with its worst adjacent pair (amber vs. teal) at
 * CVD ΔE 8.4 — inside the target band, but close enough that a protan/tritan
 * viewer with two components toggled on benefits from a second channel. Solid
 * is reserved for the composite (the emphasis series), so components each get
 * a distinct dash pattern; the legend swatch mirrors it exactly (both are
 * driven by this same prop on <Line>, see renderLegend).
 */
const COMPONENT_DASH: Record<string, string> = {
  ntnu_fitness: "5 3",
  hrv_norm: "1 3",
  steps_mortality: "8 3 2 3",
  kdm: "11 3",
};

const COMPONENT_LABELS: Record<string, string> = {
  kdm: "KDM",
  ntnu_fitness: "Fitness age (NTNU)",
  hrv_norm: "HRV age",
  steps_mortality: "Step-count age",
};

/**
 * A component's 95% interval from its own sigma_years (age ± 1.96·sigma —
 * same z-score the backend composite uses, see
 * backend/src/bioage/reference/composite.yaml). No estimate is rendered
 * without its uncertainty; components don't get a fifth shaded band (that
 * would bury the composite), so their interval surfaces on hover instead.
 */
function componentInterval(age: number, sigma: number | undefined): string | null {
  if (sigma === undefined || !Number.isFinite(sigma)) return null;
  const halfWidth = 1.96 * sigma;
  return `${formatYears(age - halfWidth)} – ${formatYears(age + halfWidth)}`;
}

/**
 * A data key's color for legend/tooltip line-keys. The low-confidence marker
 * is intentionally *hollow* on the chart (fill = surface, stroke = accent) —
 * but a swatch or tooltip row filled with the surface color is invisible
 * against the surface it sits on. Off-chart UI always keys on the accent
 * (the color that actually reads), never the mark's literal fill.
 */
function colorForDataKey(dataKey: unknown): string {
  const key = typeof dataKey === "string" ? dataKey : "";
  switch (key) {
    case "chronoAge":
      return CHART_MUTED;
    case "band":
    case "bioAge":
    case "lowConfidencePoint":
      return CHART_ACCENT;
    default:
      return COMPONENT_COLORS[key.replace(/^c_/, "")] ?? CHART_MUTED;
  }
}

interface Props {
  points: SeriesPoint[];
  visibleComponents: string[];
}

interface LegendEntry {
  value: ReactNode;
  type?: string;
  color?: string;
  dataKey?: unknown;
  /** Recharts attaches the originating <Line>/<Area>/<Scatter>'s own props
   * here (see recharts/lib/util/getLegendProps.js), including strokeDasharray
   * — reading it back out keeps the legend's dash pattern and the plot's
   * dash pattern structurally the same value, not two numbers kept in sync
   * by convention. */
  payload?: { strokeDasharray?: string | number };
}

/**
 * Custom legend content: the swatch carries the series color (and, for
 * component lines, the same dash pattern drawn on the chart), the text never
 * does ("Text never wears the data color" — marks-and-anatomy.md). Recharts'
 * default legend colors both by the mark's own fill, which is how the
 * hollow low-confidence marker's surface-colored fill silently produced
 * invisible legend/tooltip text — this sidesteps that entirely.
 */
function renderLegend({ payload }: { payload?: LegendEntry[] }) {
  if (!payload || payload.length === 0) return null;
  return (
    <ul className="chart-legend">
      {payload.map((entry) => {
        const color = colorForDataKey(entry.dataKey) || entry.color || CHART_MUTED;
        const dash = entry.payload?.strokeDasharray;
        return (
          <li key={String(entry.value)}>
            <svg className="chart-legend-swatch" width="16" height="12" aria-hidden="true">
              {entry.type === "rect" ? (
                <rect x="1" y="3" width="14" height="7" rx="1.5" fill={color} />
              ) : entry.type === "circle" ? (
                <circle cx="8" cy="6" r="4" fill="none" stroke={color} strokeWidth="1.5" />
              ) : (
                <line
                  x1="0"
                  y1="6"
                  x2="16"
                  y2="6"
                  stroke={color}
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeDasharray={dash}
                />
              )}
            </svg>
            {entry.value}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Custom tooltip content, per the dataviz skill: values lead (Strong,
 * high-contrast), the series name follows (secondary ink), and each row
 * keys on a short stroke of the series color rather than a filled box.
 *
 * Component rows also carry their own 95% interval in parentheses — the
 * chart draws components as plain lines (four more shaded bands would make
 * it unreadable), so the uncertainty has to live somewhere, and it can never
 * simply be omitted. `entry.payload` is Recharts' full data row at that X
 * (see DefaultTooltipContent's `payload?: any`), which is where the
 * `s_<key>` sigma flattened alongside each `c_<key>` age actually lives.
 */
function renderTooltip({ active, label, payload }: TooltipProps<number | [number, number], string>) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="chart-tooltip">
      <p className="chart-tooltip-label">Week of {label}</p>
      <ul>
        {payload.map((entry) => {
          const dataKey = typeof entry.dataKey === "string" ? entry.dataKey : "";
          const value = entry.value;
          const text = Array.isArray(value)
            ? `${formatYears(value[0])} – ${formatYears(value[1])}`
            : formatYears(value as number);
          const componentKey = dataKey.startsWith("c_") ? dataKey.slice(2) : null;
          const interval =
            componentKey && typeof value === "number"
              ? componentInterval(value, entry.payload?.[`s_${componentKey}`])
              : null;
          return (
            <li key={dataKey}>
              <span
                className="chart-legend-swatch chart-legend-swatch--line"
                style={{ background: colorForDataKey(entry.dataKey) }}
              />
              <strong>{text}</strong>
              {interval && <span className="chart-tooltip-interval">({interval})</span>}
              <span className="chart-tooltip-name">{entry.name}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function BioAgeChart({ points, visibleComponents }: Props) {
  if (points.length === 0) {
    return (
      <div className="empty-state">
        <p>No biological age data yet.</p>
        <p className="muted">
          Connect Google Health and sync, or seed demo data to see the chart.
        </p>
      </div>
    );
  }

  const rows = toChartRows(points).map((row) => ({
    ...row,
    ...Object.fromEntries(
      Object.entries(row.componentAges).map(([key, value]) => [`c_${key}`, value]),
    ),
    // Sigma travels alongside each component's age under a matching `s_`
    // key so the tooltip (which receives the full row via entry.payload)
    // can compute that component's own interval without a second lookup.
    ...Object.fromEntries(
      Object.entries(row.componentSigmas).map(([key, value]) => [`s_${key}`, value]),
    ),
    lowConfidencePoint: row.lowConfidence ? row.bioAge : undefined,
  }));

  return (
    <ResponsiveContainer width="100%" height={420}>
      <ComposedChart data={rows} margin={{ top: 16, right: 24, bottom: 24, left: 8 }}>
        {/* Gridlines are solid hairlines, never dashed — dashing is reserved for
            the chronological-age reference line, where it signals "not the subject." */}
        <CartesianGrid stroke={CHART_GRIDLINE} vertical={false} />
        <XAxis
          dataKey="week"
          tick={{ fontSize: 12, fill: CHART_MUTED }}
          axisLine={{ stroke: CHART_BASELINE }}
          tickLine={{ stroke: CHART_BASELINE }}
          minTickGap={28}
        />
        <YAxis
          tick={{ fontSize: 12, fill: CHART_MUTED }}
          axisLine={{ stroke: CHART_BASELINE }}
          tickLine={{ stroke: CHART_BASELINE }}
          domain={["dataMin - 3", "dataMax + 3"]}
          label={{
            value: "Age (years)",
            angle: -90,
            position: "insideLeft",
            fontSize: 12,
            fill: CHART_MUTED,
          }}
        />
        <Tooltip cursor={{ stroke: CHART_BASELINE }} content={renderTooltip} />
        <Legend content={renderLegend} />

        {/* The 95% interval is the subject's uncertainty, always on screen —
            a wash at ~10% opacity, never a saturated block. */}
        <Area
          dataKey="band"
          name="95% interval"
          stroke="none"
          fill={CHART_ACCENT}
          fillOpacity={0.1}
          legendType="rect"
          isAnimationActive={false}
        />
        {/* The gap is the subject: chronological age is a dashed de-emphasis
            reference, not another series competing for the same identity slot. */}
        <Line
          dataKey="chronoAge"
          name="Chronological age"
          stroke={CHART_MUTED}
          strokeWidth={2}
          strokeDasharray="6 4"
          dot={false}
          isAnimationActive={false}
        />
        <Line
          dataKey="bioAge"
          name="Biological age"
          stroke={CHART_ACCENT}
          strokeWidth={2}
          dot={{ r: 4, fill: CHART_ACCENT, strokeWidth: 0 }}
          isAnimationActive={false}
        />
        {/* Thin weeks get a hollow marker so low confidence is visible, not just encoded. */}
        <Scatter
          dataKey="lowConfidencePoint"
          name="Low data coverage"
          fill={CHART_SURFACE}
          stroke={CHART_ACCENT}
          strokeWidth={2}
          shape="circle"
          legendType="circle"
        />

        {visibleComponents.map((key) => (
          <Line
            key={key}
            dataKey={`c_${key}`}
            name={COMPONENT_LABELS[key] ?? key}
            stroke={COMPONENT_COLORS[key] ?? CHART_MUTED}
            strokeWidth={2}
            strokeDasharray={COMPONENT_DASH[key]}
            dot={false}
            isAnimationActive={false}
          />
        ))}
      </ComposedChart>
    </ResponsiveContainer>
  );
}
