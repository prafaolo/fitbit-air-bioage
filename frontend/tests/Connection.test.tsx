import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { getSyncStatus } from "../src/api/client";
import { Connection } from "../src/pages/Connection";
import type { SyncStatus } from "../src/api/types";

vi.mock("../src/api/client", () => ({
  getSyncStatus: vi.fn(),
  triggerSync: vi.fn(),
  authStartUrl: () => "http://localhost:8000/api/auth/google/start",
}));

/** A promise whose resolution is controlled from the test body, so the
 * pending (loading) state can be asserted before letting the fetch settle. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

describe("Connection", () => {
  it("shows a neutral loading state before the status fetch resolves, not a wrong connection status", async () => {
    const { promise, resolve } = deferred<SyncStatus>();
    vi.mocked(getSyncStatus).mockReturnValue(promise);

    render(<Connection />);

    // Before the fetch resolves, status is still null — asserting "Not
    // connected" here would misrepresent a user who is actually connected,
    // so only the neutral loading copy may appear.
    expect(screen.getByText(/checking connection/i)).toBeDefined();
    expect(screen.queryByText(/not connected/i)).toBeNull();
    expect(screen.queryByText(/connected to google health/i)).toBeNull();

    resolve({ connected: true, data_types: [] });

    await waitFor(() =>
      expect(screen.getByText(/connected to google health/i)).toBeDefined(),
    );
    expect(screen.queryByText(/checking connection/i)).toBeNull();
  });

  it("shows Not connected once the fetch resolves with connected: false", async () => {
    vi.mocked(getSyncStatus).mockResolvedValue({ connected: false, data_types: [] });

    render(<Connection />);

    await waitFor(() => expect(screen.getByText(/not connected/i)).toBeDefined());
  });
});
