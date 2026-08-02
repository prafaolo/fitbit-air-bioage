import type { Measurement } from "../api/types";

const LABELS: Record<Measurement["kind"], string> = {
  height_m: "Height (m)",
  weight_kg: "Weight (kg)",
  waist_cm: "Waist (cm)",
};

interface Props {
  measurements: Measurement[];
  onDelete: (id: number) => void;
}

export function MeasurementTable({ measurements, onDelete }: Props) {
  if (measurements.length === 0) {
    return <p className="muted">No measurements recorded yet.</p>;
  }
  return (
    <table>
      <thead>
        <tr>
          <th>Measurement</th>
          <th>Value</th>
          <th>Measured on</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {measurements.map((m) => (
          <tr key={m.id}>
            <td>{LABELS[m.kind]}</td>
            <td>{m.value}</td>
            <td>{m.measured_on}</td>
            <td>
              <button onClick={() => onDelete(m.id)} aria-label={`Remove ${LABELS[m.kind]}`}>
                Remove
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
