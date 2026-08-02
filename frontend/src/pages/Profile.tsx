import { useEffect, useState } from "react";

import { addMeasurement, deleteMeasurement, getProfile, putProfile } from "../api/client";
import type { Measurement, Profile } from "../api/types";
import { MeasurementTable } from "../components/MeasurementTable";

const KIND_LABELS: Record<Measurement["kind"], string> = {
  height_m: "Height (m)",
  weight_kg: "Weight (kg)",
  waist_cm: "Waist (cm)",
};

const KINDS: Measurement["kind"][] = ["height_m", "weight_kg", "waist_cm"];

/** GET /api/profile returns 404 before any profile has been saved — that is
 * a normal first-run state, not a failure, so it is distinguished from other
 * fetch errors (network failure, 500) which should be surfaced to the user. */
function isNotFound(error: unknown): boolean {
  return error instanceof Error && error.message.startsWith("404");
}

export function ProfilePage() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Starts true so the first render doesn't assert "No profile set up yet"
  // (profile is still null at that point) for a user who does have one —
  // that copy is only trustworthy once the initial fetch has resolved.
  const [loading, setLoading] = useState(true);
  const [sex, setSex] = useState<Profile["sex"]>("male");
  const [birthdate, setBirthdate] = useState("");
  const [kind, setKind] = useState<Measurement["kind"]>("waist_cm");
  const [value, setValue] = useState("");
  const [measuredOn, setMeasuredOn] = useState(() => new Date().toISOString().slice(0, 10));
  const [message, setMessage] = useState<string | null>(null);

  const reload = async () => {
    try {
      const p = await getProfile();
      setProfile(p);
      setSex(p.sex);
      setBirthdate(p.birthdate);
      setLoadError(null);
    } catch (e) {
      if (isNotFound(e)) {
        setProfile(null);
        setLoadError(null);
      } else {
        setLoadError((e as Error).message);
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void reload();
  }, []);

  const saveProfile = async () => {
    try {
      const saved = await putProfile({ sex, birthdate });
      setProfile(saved);
      setLoadError(null);
      setMessage("Profile saved. Scores were recomputed.");
    } catch (e) {
      setMessage((e as Error).message);
    }
  };

  const saveMeasurement = async () => {
    try {
      await addMeasurement({ kind, value: Number(value), measured_on: measuredOn });
      setValue("");
      setMessage(`${KIND_LABELS[kind]} recorded for ${measuredOn}. Scores were recomputed.`);
      await reload();
    } catch (e) {
      setMessage((e as Error).message);
    }
  };

  const remove = async (id: number) => {
    try {
      await deleteMeasurement(id);
      setMessage("Measurement removed. Scores were recomputed.");
      await reload();
    } catch (e) {
      setMessage((e as Error).message);
    }
  };

  return (
    <section>
      <h1>Profile</h1>
      <p className="muted">
        Waist circumference and body size cannot be measured by the band, so they are entered
        here by hand. Every measurement is dated: adding a new waist reading today does not
        rewrite a score computed for a week months ago — each week's score uses whichever
        measurement was current as of that week.
      </p>

      {loading ? (
        <p className="muted">Loading profile…</p>
      ) : loadError ? (
        <p className="error">Could not load profile: {loadError}</p>
      ) : (
        !profile && (
          <p className="muted">
            No profile set up yet — enter your sex and birthdate below to get started.
          </p>
        )
      )}

      <h2>Identity</h2>
      <div className="form-row">
        <select
          value={sex}
          onChange={(e) => setSex(e.target.value as Profile["sex"])}
          aria-label="Sex"
        >
          <option value="male">Male</option>
          <option value="female">Female</option>
        </select>
        <input
          type="date"
          value={birthdate}
          onChange={(e) => setBirthdate(e.target.value)}
          aria-label="Birthdate"
        />
        <button onClick={() => void saveProfile()} disabled={!birthdate}>
          Save
        </button>
      </div>

      <h2>Measurements</h2>
      <p className="muted">
        These feed the fitness-age and Klemera&ndash;Doubal estimators, which the band alone
        cannot supply.
      </p>
      <div className="form-row">
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as Measurement["kind"])}
          aria-label="Measurement type"
        >
          {KINDS.map((k) => (
            <option key={k} value={k}>
              {KIND_LABELS[k]}
            </option>
          ))}
        </select>
        <input
          type="number"
          step="0.1"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Value"
          aria-label="Measurement value"
        />
        <input
          type="date"
          value={measuredOn}
          onChange={(e) => setMeasuredOn(e.target.value)}
          aria-label="Measured on"
        />
        <button onClick={() => void saveMeasurement()} disabled={!value}>
          Add
        </button>
      </div>

      <MeasurementTable measurements={profile?.measurements ?? []} onDelete={(id) => void remove(id)} />
      {message && <p className="muted">{message}</p>}
    </section>
  );
}
