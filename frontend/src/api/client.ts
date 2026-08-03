import type {
  AuthStatus,
  Measurement,
  Profile,
  SeriesPoint,
  SyncStatus,
  SyncTriggerAck,
  WeekDetail,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${body}`);
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

export const getSeries = () => request<SeriesPoint[]>("/api/bioage/series");

export const getWeek = (weekStart: string) =>
  request<WeekDetail>(`/api/bioage/weeks/${weekStart}`);

export const getProfile = () => request<Profile>("/api/profile");

export const putProfile = (profile: Pick<Profile, "sex" | "birthdate">) =>
  request<Profile>("/api/profile", {
    method: "PUT",
    body: JSON.stringify(profile),
  });

export const addMeasurement = (
  measurement: Pick<Measurement, "kind" | "value" | "measured_on">,
) =>
  request<Measurement>("/api/profile/measurements", {
    method: "POST",
    body: JSON.stringify(measurement),
  });

export const deleteMeasurement = (id: number) =>
  request<void>(`/api/profile/measurements/${id}`, { method: "DELETE" });

export const getSyncStatus = () => request<SyncStatus>("/api/sync/status");

/** Schedules the sync as a background job and returns as soon as it's queued (202) —
 * the outcome is not in this response, poll getSyncStatus() (SyncStatus.sync) for it. */
export const triggerSync = () => request<SyncTriggerAck>("/api/sync", { method: "POST" });

export const getAuthStatus = () => request<AuthStatus>("/api/auth/google/status");

/** GET /api/auth/google/start is a 302 redirect (or 503 if unconfigured) —
 * not JSON, so it is navigated to directly rather than fetched. */
export const authStartUrl = () => `${BASE}/api/auth/google/start`;
