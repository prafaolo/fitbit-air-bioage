export interface Component {
  component: string;
  age_years: number;
  sigma_years: number;
  inputs: Record<string, number>;
}

export interface SeriesPoint {
  week_start: string;
  chronological_age: number;
  composite_age: number;
  ci_low: number;
  ci_high: number;
  is_low_confidence: boolean;
  components: Component[];
}

export interface WeekDetail extends SeriesPoint {
  coverage: Record<string, number | boolean>;
}

export interface Measurement {
  id: number;
  kind: "height_m" | "weight_kg" | "waist_cm";
  value: number;
  measured_on: string;
}

export interface Profile {
  sex: "male" | "female";
  birthdate: string;
  measurements: Measurement[];
}

export interface CoverageRow {
  data_type: string;
  synced_through: string | null;
  last_run_at: string | null;
  last_error: string | null;
  expected_empty: boolean;
  points_stored: number;
}

/** One data type's outcome from the last completed sync run. `parse_errors` counts
 * records that failed to parse (not a list) — added to the backend after
 * the original schema draft. */
export interface SyncReport {
  data_type: string;
  days_written: number;
  error: string | null;
  parse_errors: number;
}

/**
 * State of the background sync job. POST /api/sync runs the sync in a FastAPI
 * BackgroundTasks job rather than inline (worst case with the retry budget is
 * minutes — too long for a synchronous "Syncing…" request) and returns immediately;
 * this is what the Connection page polls via GET /api/sync/status until `running`
 * goes back to false.
 */
export interface SyncRun {
  running: boolean;
  started_at: string | null;
  finished_at: string | null;
  last_weeks_scored: number | null;
  last_reports: SyncReport[] | null;
  last_error: string | null;
}

export interface SyncStatus {
  connected: boolean;
  data_types: CoverageRow[];
  sync: SyncRun;
}

/** Immediate response to POST /api/sync — the run itself happens in the background;
 * poll getSyncStatus() (SyncStatus.sync) for its outcome. */
export interface SyncTriggerAck {
  status: string;
}

export interface AuthStatus {
  connected: boolean;
  connected_at: string | null;
  scopes: string[];
}
