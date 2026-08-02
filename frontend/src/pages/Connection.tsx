import { useEffect, useState } from "react";

import { authStartUrl, getSyncStatus, triggerSync } from "../api/client";
import type { SyncStatus, SyncTriggerResult } from "../api/types";
import { CoverageTable } from "../components/CoverageTable";

export function Connection() {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [lastSync, setLastSync] = useState<SyncTriggerResult | null>(null);

  const reload = async () => {
    try {
      const s = await getSyncStatus();
      setStatus(s);
      setStatusError(null);
    } catch (e) {
      setStatus(null);
      setStatusError((e as Error).message);
    }
  };

  useEffect(() => {
    void reload();
  }, []);

  const sync = async () => {
    setSyncing(true);
    setMessage(null);
    try {
      const result = await triggerSync();
      setLastSync(result);
      const hasIssues = result.reports.some((r) => r.error || r.parse_errors > 0);
      setMessage(
        hasIssues
          ? `Sync finished with issues — ${result.weeks_scored} week(s) rescored. See the report below.`
          : `Sync complete — ${result.weeks_scored} week(s) rescored.`,
      );
      await reload();
    } catch (e) {
      setLastSync(null);
      // client.ts formats non-ok responses as "<status> <statusText>: <body>",
      // e.g. "409 Conflict: ..." when not connected — useful text, not a
      // stack trace, so it is safe to show directly.
      setMessage((e as Error).message);
    } finally {
      setSyncing(false);
    }
  };

  return (
    <section>
      <h1>Connection</h1>

      {statusError && <p className="error">Could not load connection status: {statusError}</p>}

      {status?.connected ? (
        <p>Connected to Google Health.</p>
      ) : (
        <p>
          Not connected. <a href={authStartUrl()}>Connect Google Health</a> — see{" "}
          <code>docs/SETUP.md</code> if this returns an error.
        </p>
      )}

      <button onClick={() => void sync()} disabled={!status?.connected || syncing}>
        {syncing ? "Syncing…" : "Sync now"}
      </button>
      {message && <p className="muted">{message}</p>}

      {lastSync && (
        <ul className="sync-report">
          {lastSync.reports.map((r) => (
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
      <CoverageTable rows={status?.data_types ?? []} />
    </section>
  );
}
