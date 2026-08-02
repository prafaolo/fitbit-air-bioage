import { useEffect, useState } from "react";

import { getSeries } from "../api/client";
import type { SeriesPoint } from "../api/types";
import { BioAgeChart } from "../components/BioAgeChart";
import { MethodologyNote } from "../components/MethodologyNote";
import { componentKeys, formatYears } from "../lib/series";

export function Dashboard() {
  const [points, setPoints] = useState<SeriesPoint[]>([]);
  const [visible, setVisible] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getSeries()
      .then(setPoints)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const latest = points.at(-1);
  const keys = componentKeys(points);

  const toggle = (key: string) =>
    setVisible((current) =>
      current.includes(key) ? current.filter((k) => k !== key) : [...current, key],
    );

  if (loading) return <p>Loading…</p>;
  if (error) return <p className="error">Could not load series: {error}</p>;

  return (
    <section>
      <header className="dashboard-header">
        <h1>Biological age</h1>
        {latest && (
          <p className="headline">
            <strong>{formatYears(latest.composite_age)}</strong> vs{" "}
            {formatYears(latest.chronological_age)} chronological
            <span className="muted">
              {" "}
              ({formatYears(latest.ci_low)}–{formatYears(latest.ci_high)})
            </span>
          </p>
        )}
      </header>

      <BioAgeChart points={points} visibleComponents={visible} />

      {keys.length > 0 && (
        <div className="component-toggles">
          <span className="muted">Show components:</span>
          {keys.map((key) => (
            <label key={key}>
              <input
                type="checkbox"
                checked={visible.includes(key)}
                onChange={() => toggle(key)}
              />
              {key}
            </label>
          ))}
        </div>
      )}

      <MethodologyNote />
    </section>
  );
}
