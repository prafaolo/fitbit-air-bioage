import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MeasurementTable } from "../src/components/MeasurementTable";
import type { Measurement } from "../src/api/types";

const measurements: Measurement[] = [
  { id: 1, kind: "waist_cm", value: 88, measured_on: "2026-05-01" },
  { id: 2, kind: "waist_cm", value: 86, measured_on: "2026-07-01" },
];

describe("MeasurementTable", () => {
  it("shows a prompt when there are no measurements", () => {
    render(<MeasurementTable measurements={[]} onDelete={vi.fn()} />);
    expect(screen.getByText(/no measurements recorded/i)).toBeDefined();
  });

  it("renders one row per measurement", () => {
    render(<MeasurementTable measurements={measurements} onDelete={vi.fn()} />);
    expect(screen.getAllByRole("row")).toHaveLength(3); // header + 2
  });

  it("shows the measurement date so history is visible", () => {
    render(<MeasurementTable measurements={measurements} onDelete={vi.fn()} />);
    expect(screen.getByText("2026-05-01")).toBeDefined();
    expect(screen.getByText("2026-07-01")).toBeDefined();
  });

  it("calls onDelete with the row id", () => {
    const onDelete = vi.fn();
    render(<MeasurementTable measurements={measurements} onDelete={onDelete} />);
    fireEvent.click(screen.getAllByRole("button", { name: /remove/i })[0]);
    expect(onDelete).toHaveBeenCalledWith(1);
  });
});
