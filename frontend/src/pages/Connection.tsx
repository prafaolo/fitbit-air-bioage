import { useEffect, useRef, useState } from "react";

import { authStartUrl, getSyncStatus, triggerSync } from "../api/client";
import type { SyncRun, SyncStatus } from "../api/types";
import { CoverageTable } from "../components/CoverageTable";

// POST /api/sync schedules the sync as a background job and returns immediately (the
// worst case with the client's retry budget is on the order of minutes -- far too long
// for a synchronous request). This page instead polls GET /api/sync/status until
// `sync.running` goes back to false.
const POLL_INTERVAL_MS = 2000;
// A safety net, not an expected outcome: bounds how long this page will keep polling
// before giving up and telling the user to check back later, rather than polling a
// stuck job forever.
const MAX_POLL_ATTEMPTS = 300; // 300 * 2s = 10 minutes

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function describeOutcome(sync: SyncRun): string {
  if (sync.last_error) {
    return `Sync failed: ${sync.last_error}`;
  }
  const reports = sync.last_reports ?? [];
  const hasIssues = reports.some((r) => r.error || r.parse_errors > 0);
  const weeks = sync.last_weeks_scored ?? 0;
  return hasIssues
    ? `Sync finished with issues — ${weeks} week(s) rescored. See the report below.`
    : `Sync complete — ${weeks} week(s) rescored.`;
}

export function Connection() {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  // Starts true so the first render — before getSyncStatus() has resolved —
  // shows a neutral "checking" state instead of asserting "Not connected"
  // (status still null at that point) for a user who may in fact be
  // connected. This page exists to be trusted as ground truth about setup,
  // so it must not assert either state before it actually knows.
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  // A background sync triggered elsewhere (the cron schedule, another tab) can already
  // be running when this page loads; that must not race a poll loop started by this
  // page's own "Sync now" click into running twice concurrently.
  const polling = useRef(false);

  const reload = async (): Promise<SyncStatus | null> => {
    try {
      const s = await getSyncStatus();
      setStatus(s);
      setStatusError(null);
      return s;
    } catch (e) {
      setStatus(null);
      setStatusError((e as Error).message);
      return null;
    } finally {
      setLoading(false);
    }
  };

  const pollUntilSettled = async () => {
    if (polling.current) return;
    polling.current = true;
    setSyncing(true);
    try {
      for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt++) {
        const s = await reload();
        if (!s) return;
        if (!s.sync.running) {
          setMessage(describeOutcome(s.sync));
          return;
        }
        await sleep(POLL_INTERVAL_MS);
      }
      setMessage("Sync is taking longer than expected — check back in a moment.");
    } finally {
      polling.current = false;
      setSyncing(false);
    }
  };

  useEffect(() => {
    void (async () => {
      const s = await reload();
      if (s?.sync.running) void pollUntilSettled();
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sync = async () => {
    setMessage(null);
    try {
      await triggerSync();
    } catch (e) {
      // client.ts formats non-ok responses as "<status> <statusText>: <body>",
      // e.g. "409 Conflict: ..." when not connected — useful text, not a
      // stack trace, so it is safe to show directly.
      setMessage((e as Error).message);
      return;
    }
    await pollUntilSettled();
  };

  const isSyncing = syncing || status?.sync.running === true;
  const lastSync = status?.sync;

  return (
    <section>
      <h1>Connection</h1>

      {loading ? (
        <p className="muted">Checking connection…</p>
      ) : statusError ? (
        <p className="error">Could not load connection status: {statusError}</p>
      ) : status?.connected ? (
        <p>Connected to Google Health.</p>
      ) : (
        <p>
          Not connected. <a href={authStartUrl()}>Connect Google Health</a> — see{" "}
          <code>docs/SETUP.md</code> if this returns an error.
        </p>
      )}

      <button onClick={() => void sync()} disabled={loading || !status?.connected || isSyncing}>
        {isSyncing ? "Syncing…" : "Sync now"}
      </button>
      {message && <p className="muted">{message}</p>}

      {lastSync?.last_reports && (
        <ul className="sync-report">
          {lastSync.last_reports.map((r) => (
            <li key={r.data_type}>
              <strong>{r.data_type}</strong>: {r.days_written} day(s) written
              {r.parse_errors > 0 && (
                <span className="error">
                  {" "}
                  — {r.parse_errors} record{r.parse_errors === 1 ? "" : "s"} failed to parse
                </span>
              )}
              {r.error && <span className="error"> — {r.error}</span>}
            </li>
          ))}
        </ul>
      )}

      <h2>Data coverage</h2>
      <p className="muted">
        The Fitbit Air derives VO<sub>2</sub>max only from GPS-tracked runs, so{" "}
        <code>daily-vo2-max</code> is expected to stay empty rather than indicate a problem.
      </p>
      {loading ? (
        <p className="muted">Loading coverage…</p>
      ) : (
        <CoverageTable rows={status?.data_types ?? []} />
      )}
    </section>
  );
}
