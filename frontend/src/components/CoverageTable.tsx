import type { CoverageRow } from "../api/types";

export function CoverageTable({ rows }: { rows: CoverageRow[] }) {
  if (rows.length === 0) {
    return <p className="muted">No coverage data yet — connect and sync to populate this table.</p>;
  }
  return (
    <table>
      <thead>
        <tr>
          <th>Data type</th>
          <th>Points stored</th>
          <th>Synced through</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.data_type}>
            <td>{row.data_type}</td>
            <td>{row.points_stored}</td>
            <td>{row.synced_through ?? "—"}</td>
            <td>
              {row.last_error ? (
                <span className="error" title={row.last_error}>
                  error: {row.last_error}
                </span>
              ) : row.points_stored === 0 && row.expected_empty ? (
                <span className="muted">empty (expected — not produced by the Air)</span>
              ) : row.points_stored === 0 ? (
                <span className="muted">no data</span>
              ) : (
                "ok"
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
