import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CoverageTable } from "../src/components/CoverageTable";
import type { CoverageRow } from "../src/api/types";

function row(overrides: Partial<CoverageRow>): CoverageRow {
  return {
    data_type: "daily-resting-heart-rate",
    synced_through: null,
    last_run_at: null,
    last_error: null,
    expected_empty: false,
    points_stored: 0,
    ...overrides,
  };
}

describe("CoverageTable", () => {
  it("shows the error text for a row with a last_error", () => {
    render(
      <CoverageTable
        rows={[row({ data_type: "steps", last_error: "upstream timed out", points_stored: 0 })]}
      />,
    );
    expect(screen.getByText(/upstream timed out/i)).toBeDefined();
  });

  it("shows expected-empty copy, not generic no-data copy, when points_stored is 0 and expected_empty is true", () => {
    render(
      <CoverageTable
        rows={[row({ data_type: "daily-vo2-max", points_stored: 0, expected_empty: true })]}
      />,
    );
    expect(screen.getByText(/expected/i)).toBeDefined();
    expect(screen.queryByText(/^no data$/i)).toBeNull();
  });

  it("shows generic no-data copy, not expected-empty copy, when points_stored is 0 and expected_empty is false", () => {
    render(
      <CoverageTable
        rows={[row({ data_type: "steps", points_stored: 0, expected_empty: false })]}
      />,
    );
    expect(screen.getByText(/^no data$/i)).toBeDefined();
    expect(screen.queryByText(/expected/i)).toBeNull();
  });

  it("shows ok when points are stored", () => {
    render(
      <CoverageTable
        rows={[
          row({
            data_type: "steps",
            points_stored: 42,
            synced_through: "2026-07-27",
            expected_empty: false,
          }),
        ]}
      />,
    );
    expect(screen.getByText("ok")).toBeDefined();
    expect(screen.getByText("2026-07-27")).toBeDefined();
  });

  it("renders one row per data type, keeping expected-empty and no-data rows visibly distinct", () => {
    render(
      <CoverageTable
        rows={[
          row({ data_type: "daily-vo2-max", points_stored: 0, expected_empty: true }),
          row({ data_type: "steps", points_stored: 0, expected_empty: false }),
        ]}
      />,
    );
    expect(screen.getAllByRole("row")).toHaveLength(3); // header + 2
    const expectedEmptyText = screen.getByText(/expected/i).textContent;
    const noDataText = screen.getByText(/^no data$/i).textContent;
    expect(expectedEmptyText).not.toBe(noDataText);
  });
});
