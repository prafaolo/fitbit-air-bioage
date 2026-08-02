import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getSyncStatus, triggerSync } from "../src/api/client";
import { Connection } from "../src/pages/Connection";
import type { SyncRun, SyncStatus } from "../src/api/types";

vi.mock("../src/api/client", () => ({
  getSyncStatus: vi.fn(),
  triggerSync: vi.fn(),
  authStartUrl: () => "http://localhost:8000/api/auth/google/start",
}));

// Several tests below queue up sequential mockResolvedValueOnce() responses to drive
// the polling loop; without a reset, unconsumed queued responses from one test would
// bleed into the next (mocks are module-level singletons, not per-test).
beforeEach(() => {
  vi.mocked(getSyncStatus).mockReset();
  vi.mocked(triggerSync).mockReset();
});

/** A promise whose resolution is controlled from the test body, so the
 * pending (loading) state can be asserted before letting the fetch settle. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

const idleSync: SyncRun = {
  running: false,
  started_at: null,
  finished_at: null,
  last_weeks_scored: null,
  last_reports: null,
  last_error: null,
};

const status = (overrides: Partial<SyncStatus> = {}): SyncStatus => ({
  connected: true,
  data_types: [],
  sync: idleSync,
  ...overrides,
});

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

    resolve(status());

    await waitFor(() =>
      expect(screen.getByText(/connected to google health/i)).toBeDefined(),
    );
    expect(screen.queryByText(/checking connection/i)).toBeNull();
  });

  it("shows Not connected once the fetch resolves with connected: false", async () => {
    vi.mocked(getSyncStatus).mockResolvedValue(status({ connected: false }));

    render(<Connection />);

    await waitFor(() => expect(screen.getByText(/not connected/i)).toBeDefined());
  });

  it("polls sync status until running settles, then reports the outcome", async () => {
    vi.mocked(getSyncStatus)
      // Initial load on mount.
      .mockResolvedValueOnce(status())
      // triggerSync's own POST returns immediately once queued; the very next poll
      // already observes it running, which forces a real inter-poll sleep before the
      // next status fetch -- giving this test a genuine window to observe "Syncing…"
      // rather than racing two back-to-back microtask resolutions.
      .mockResolvedValueOnce(status({ sync: { ...idleSync, running: true } }))
      .mockResolvedValueOnce(
        status({
          sync: {
            running: false,
            started_at: "2026-08-02T05:00:00Z",
            finished_at: "2026-08-02T05:00:05Z",
            last_weeks_scored: 3,
            last_reports: [
              { data_type: "steps", days_written: 10, error: null, parse_errors: 0 },
            ],
            last_error: null,
          },
        }),
      );
    vi.mocked(triggerSync).mockResolvedValue({ status: "started" });

    render(<Connection />);
    await waitFor(() => expect(screen.getByText(/connected to google health/i)).toBeDefined());

    fireEvent.click(screen.getByRole("button", { name: /sync now/i }));

    // While the poll observes running: true, the button reads "Syncing…" and is
    // disabled, not clickable again.
    const syncingButton = await waitFor(() =>
      screen.getByRole("button", { name: /syncing/i }),
    );
    expect((syncingButton as HTMLButtonElement).disabled).toBe(true);

    await waitFor(
      () => expect(screen.getByText(/sync complete.*3 week/i)).toBeDefined(),
      { timeout: 3000 },
    );
    // The report row's text is split across sibling nodes (<strong>steps</strong>: 10
    // day(s) written), so match on the list's combined text content rather than a
    // single-node getByText, which only matches text within one element.
    expect(document.querySelector(".sync-report")?.textContent).toMatch(/steps.*10 day/i);
    const idleButton = screen.getByRole("button", { name: /^sync now$/i });
    expect((idleButton as HTMLButtonElement).disabled).toBe(false);
  });

  it("polls automatically on load when a sync is already running (e.g. a scheduled run)", async () => {
    vi.mocked(getSyncStatus)
      .mockResolvedValueOnce(status({ sync: { ...idleSync, running: true } }))
      // Still running on the poll loop's first check -- forces a real sleep before the
      // next fetch, the same real macrotask gap the previous test relies on to make
      // the intermediate "Syncing…" render reliably observable.
      .mockResolvedValueOnce(status({ sync: { ...idleSync, running: true } }))
      .mockResolvedValueOnce(
        status({ sync: { ...idleSync, running: false, last_weeks_scored: 1, last_reports: [] } }),
      );

    render(<Connection />);

    await waitFor(() => expect(screen.getByRole("button", { name: /syncing/i })).toBeDefined());
    await waitFor(
      () => expect(screen.getByRole("button", { name: /^sync now$/i })).toBeDefined(),
      { timeout: 3000 },
    );
    expect(triggerSync).not.toHaveBeenCalled();
  });

  it("shows the sync failure message returned by client.ts instead of a stack trace", async () => {
    vi.mocked(getSyncStatus).mockResolvedValue(status());
    vi.mocked(triggerSync).mockRejectedValue(new Error("409 Conflict: Not connected"));

    render(<Connection />);
    await waitFor(() => expect(screen.getByText(/connected to google health/i)).toBeDefined());

    fireEvent.click(screen.getByRole("button", { name: /sync now/i }));

    await waitFor(() => expect(screen.getByText(/409 Conflict/)).toBeDefined());
  });
});
