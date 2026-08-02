# Fitbit Air → Biological Age: Design

**Date:** 2026-08-02
**Status:** Approved

## 1. Purpose

A self-hosted, single-user web application that pulls personal wearable data from the
Google Health API (Google Fitbit Air), derives a weekly biological-age estimate, and
plots that estimate against time.

The headline deliverable is a 2D chart: **estimated biological age (y) against calendar
week (x)**, with one point per ISO week covering the full span of available Google Health
data.

The project will be open-sourced, so every equation, constant, and approximation must be
documented and cited, and the application must be runnable by a stranger without access
to the author's credentials.

### Explicit non-goals

- No Google Takeout importer. The author has no Fitbit history predating the device.
- No legacy Fitbit Web API support. It is decommissioned in September 2026.
- No VO₂max-dependent estimator. The Air does not populate VO₂max.
- No multi-user support, no app-level authentication, no public deployment.
- No CosinorAge. It requires raw accelerometry the Air does not expose.

## 2. Honest framing

A Fitbit-only biological age is a **fitness and autonomic proxy, not a validated aging
clock**. Absolute values carry error bars of several years. The longitudinal trend is
substantially more reliable than any single point.

This framing is not merely a README disclaimer — it is a design constraint:

- Every estimate is stored and rendered with a confidence interval, never as a bare number.
- The UI draws chronological age as a reference line, making the *gap* the visual subject.
- Weeks with thin data are visually distinguished, not silently averaged in.
- Low-reliability signals (SpO₂, skin temperature) never enter as single-night values.

## 3. Architecture

Monorepo, three containers orchestrated by `docker-compose`: `postgres`, `backend`
(FastAPI + uvicorn), `frontend` (Vite). Single-user, bound to localhost, no login.

```
fitbit-air-bioage/
├── backend/
│   ├── pyproject.toml            # uv-managed
│   ├── alembic.ini
│   ├── alembic/versions/
│   ├── src/bioage/
│   │   ├── config.py             # pydantic-settings
│   │   ├── cli.py                # sync / rescore / seed-demo
│   │   ├── db/                   # SQLAlchemy models, session factory
│   │   ├── ingest/               # OAuth, HTTP client, data-type registry, sync service
│   │   ├── biomarkers/           # parsers, daily normalization, rolling-window features
│   │   ├── estimators/           # pure math: ntnu, hrv_norm, steps_mortality, kdm, composite
│   │   ├── reference/            # normative constants (YAML + citations) and loaders
│   │   ├── scoring.py            # weekly scoring orchestration
│   │   └── api/                  # FastAPI routers
│   └── tests/
├── frontend/                     # React + TypeScript + Vite
├── docs/
│   ├── SETUP.md                  # step-by-step Google Cloud setup for the author
│   ├── METHODOLOGY.md            # every equation, constant, citation, caveat
│   └── superpowers/specs/
├── docker-compose.yml
└── README.md
```

### Design principle: isolation of pure logic

All scientific logic lives in `estimators/` and `biomarkers/features.py` as **pure
functions with no database, network, or filesystem access**. They take dataclasses in and
return dataclasses out. This is what makes the model exhaustively testable and what makes
the repository auditable by a reader who does not want to run it.

I/O concerns — HTTP, OAuth, persistence, scheduling — are confined to `ingest/`, `db/`,
and `api/`, and never leak into the math.

## 4. Data pipeline

Four stages, each independently testable.

### Stage 1 — Ingest

Target: `GET https://health.googleapis.com/v4/users/me/dataTypes/{dataType}/dataPoints`

Note that the base host is `health.googleapis.com`, **not** the `healthapi.googleapis.com`
guessed in `reference-research-from-claude.md`. This was verified against the live REST
reference on 2026-08-02.

A `DATA_TYPES` registry is the single source of truth, one entry per data type holding:

| Field | Purpose |
|---|---|
| `data_type_id` | Path segment, e.g. `daily-resting-heart-rate` |
| `filter_field` | Filter expression prefix, e.g. `dailyHeartRateVariability.date` |
| `max_window_days` | Query range cap — **14 for `steps`, 90 for all others** |
| `scope` | Required OAuth scope |
| `parser` | Pure function: raw JSON → typed daily record |
| `page_size` | 1440 default; 25 for sleep |

Data types consumed:

- `daily-resting-heart-rate` — primary signal
- `daily-heart-rate-variability` — primary signal. Verified against the live RPC reference:
  this type exposes `deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds` (true
  nightly RMSSD, the input the HRV-norm estimator wants) alongside
  `averageHeartRateVariabilityMilliseconds`, `nonRemHeartRateBeatsPerMinute`, and `entropy`.
  RMSSD is used as the primary HRV input, with the average as fallback.
- `steps` — primary signal (14-day query cap)
- `sleep` — architecture, efficiency, regularity
- `daily-respiratory-rate` — secondary
- `daily-oxygen-saturation` — trend only
- `daily-sleep-temperature-derivations` — trend only
- `weight`, `height` — profile fallback if logged in Google Health. **Manually entered
  measurements always take precedence**; an API-sourced value is used for a given week only
  when no manual measurement exists on or before that week. Waist is never available from
  the API and must always be entered manually.
- `active-zone-minutes` — physical activity index input
- `vo2-max` — polled and expected empty; surfaced in the coverage table as confirmation

The exact `filter_field` name per data type must be read from the live data-types page at
implementation time; the registry design isolates that risk to a single constant per type.

`GoogleHealthClient` responsibilities, all driven generically off the registry:

- Bearer auth with automatic access-token refresh
- Cursor pagination via `nextPageToken`
- Retry with exponential backoff on 429 and 5xx
- **Window chunking**: a requested range longer than `max_window_days` is split into
  sequential sub-requests. A 60-day `steps` backfill must issue five requests of ≤14 days.
- AIP-160 filter expression construction

OAuth uses the **web authorization-code flow** exposed as backend routes
(`/api/auth/google/start` → Google consent → `/api/auth/google/callback`), not
`InstalledAppFlow.run_local_server`, which cannot work from inside a container. The
refresh token is persisted in Postgres. Google refresh tokens are reusable, so unattended
scheduling requires no token rotation dance.

**Sync triggers.** Two paths, both calling the same `SyncService`:

1. Manual — `POST /api/sync`, wired to a button on the Connection page.
2. Scheduled — an in-process APScheduler job running a daily incremental sync,
   controlled by `SYNC_SCHEDULE_ENABLED` (default `false`) and `SYNC_SCHEDULE_CRON` in
   `.env`. Off by default so the app never makes unexpected network calls on first run.

Incremental syncs read a per-data-type watermark and fetch only from the last successful
point forward; the first sync backfills as far as each data type's query window allows.

### Stage 2 — Raw store

Every datapoint is persisted to `raw_data_points` **before** any parsing:

```
raw_data_points(id, data_type, point_date, payload JSONB, ingested_at,
                UNIQUE(data_type, point_date))
```

Rationale: the Google Health API launched March 2026 and Google warned of breaking
changes. Storing raw payloads means a parser bug is fixed by re-parsing local data, not by
re-fetching data that may have aged out of the queryable window. This also makes the
parsers testable against real captured payloads without network access.

### Stage 3 — Normalize

One pure parser per data type maps raw JSONB to a `daily_metrics` row:

```
daily_metrics(date PK, rhr_bpm, hrv_rmssd_ms, steps, active_zone_minutes,
              sleep_total_min, sleep_efficiency_pct, waso_min,
              deep_pct, rem_pct, sleep_midpoint_local_min,
              respiratory_rate_brpm, spo2_pct, skin_temp_delta_c)
```

`sleep_midpoint_local_min` (minutes past local midnight) is retained specifically to
support the sleep-regularity feature.

**Sleep efficiency and WASO are derived, not provided.** The live `Sleep` message carries
only `session` (start/end), `sleepSummary.totalDuration`, and per-stage durations in
`sleepSummary.stageSummary[]` plus a `sleepStages[]` timeline. Therefore:

- `time_in_bed = session.endTime − session.startTime`
- `asleep = LIGHT + DEEP + REM stage durations`
- `sleep_efficiency_pct = asleep / time_in_bed × 100`
- `waso_min = AWAKE stage durations occurring strictly between the first and last
  non-awake stage` (leading/trailing wakefulness is not WASO)
- `deep_pct`, `rem_pct` are fractions of `asleep`, not of `time_in_bed`

Records with `sleepMetadata.stagesState != STAGES_AVAILABLE` yield duration only; stage
derived fields are null and those nights are excluded from stage-dependent features.

Proto JSON encoding notes the parsers must honour: `Date` is `{year, month, day}` (not an
ISO string), `Duration` is a string like `"28800s"`, and `int64` fields
(`beatsPerMinute`, step `count`) arrive as **strings**, not numbers.

### Stage 4 — Score

For each ISO week from the first week with data through the latest:

1. Build a **30-day trailing feature window** ending at the week's end
   (medians, not means, to resist outliers).
2. Load the profile **as of that week** — dated measurement rows mean a waist
   re-measurement does not retroactively rewrite earlier points.
3. Run every estimator whose inputs are available.
4. Combine into a composite with a confidence interval.
5. Persist to `bioage_scores`.

```
bioage_scores(week_start PK, chronological_age, composite_age,
              ci_low, ci_high, components JSONB, coverage JSONB,
              is_low_confidence, computed_at)
```

Scoring is **idempotent** — a re-run for a week overwrites its row. It is triggered after
any sync and after any profile change.

#### Warm-up and coverage gating

A week produces a point only if its trailing 30-day window contains **≥14 days of data**
and satisfies per-biomarker minimums (≥10 RHR days, ≥10 HRV nights, ≥14 step days for
those components to participate). Weeks that qualify but fall below a comfort threshold of
21 days are flagged `is_low_confidence`, receive a widened CI, and render as hollow
markers. Weeks below the hard threshold produce no point at all rather than a misleading
one.

## 5. The biological age model

### 5.1 NTNU/HUNT non-exercise Fitness Age

Nes et al. 2011, *Scand J Med Sci Sports*, HUNT Fitness Study (n=3,320), SEE ≈ ±3.5
ml/kg/min.

```
VO₂max_men   = 100.27 − 0.296·age + 0.226·PA − 0.369·WC − 0.155·RHR
VO₂max_women =  74.74 − 0.247·age + 0.198·PA − 0.259·WC − 0.114·RHR
```

Fitness age is obtained by inverting the same equation at reference PA/WC/RHR values and
solving for age:

```
fitness_age_men = (100.27 + 0.226·PA_ref − 0.369·WC_ref − 0.155·RHR_ref − VO₂max_you) / 0.296
```

Using the same equation for both directions makes the estimator self-consistent and gives
tests exact analytic expectations: substituting the reference inputs must return the
subject's chronological age to within floating-point tolerance.

**Known approximation — the PA index.** HUNT's `PA` is a questionnaire-derived index
(frequency × duration × intensity), not a step count. Steps and Active Zone Minutes are
mapped onto that index through a documented lookup table in
`reference/pa_index.yaml`. This is the least defensible input in the estimator; it is
flagged as such in code comments, in `METHODOLOGY.md`, and in the UI's methodology note.

### 5.2 HRV-norm age

The 30-day median nightly RMSSD is inverted against age/sex normative medians (~60 ms at
25y, ~43 ms in the 40s, ~34 ms in the 50s, ~31 ms in the 60s), fitted as a log-linear
decline. Consumer wrist PPG HRV is materially noisier than ECG (MAPE frequently >10%), so
this component carries a deliberately large variance in the composite.

### 5.3 Step-count mortality-equivalent age

Paluch et al. 2022, *Lancet Public Health* 7(3):e219–228 (meta-analysis, 47,471 adults).
The dose–response curve maps mean daily steps to an all-cause mortality hazard ratio; that
hazard is then matched against age-stratified baseline hazard to yield the age at which
the population's hazard equals the subject's.

### 5.4 KDM (Klemera–Doubal)

Generic over a set of `BiomarkerReference(q, k, s)` per biomarker j, where the reference
population satisfies `x_j = q_j + k_j·age + s_j`:

```
BA_E = Σⱼ [(xⱼ − qⱼ)·kⱼ/sⱼ²] / Σⱼ [kⱼ²/sⱼ²]
```

with the corrected form incorporating the characteristic variance s²_BA to shrink toward
chronological age (CA):

```
BA_EC = [ Σⱼ((xⱼ−qⱼ)kⱼ/sⱼ²) + CA/s²_BA ] / [ Σⱼ(kⱼ²/sⱼ²) + 1/s²_BA ]
```

> **Correction.** `reference-research-from-claude.md` states the denominator as
> `Σⱼ(kⱼ/sⱼ²)²`. That is incorrect: a subject lying exactly on the reference regression
> (`xⱼ = qⱼ + kⱼ·A` for all j) must yield `BA_E = A`, and only the `Σ kⱼ²/sⱼ²` denominator
> satisfies that identity. The identity is enforced as a required unit test.

Biomarkers used: RHR, BMI, HRV RMSSD, mean daily steps, sleep efficiency.

**Known limitation — derived reference constants.** There is no published NHANES q/k/s
table for wearable-derived biomarkers. The constants are therefore derived by fitting a
linear age trend through *published age-stratified normative means and standard
deviations*. Consequences, stated plainly:

- This is **"KDM-style," not the published NHANES KDM**. The estimator's math is faithful;
  its reference population is reconstructed rather than primary.
- Constants live in `reference/kdm_biomarkers.yaml`. Every entry carries a `source`
  citation and a `derived: true` flag.
- A checked-in script regenerates the YAML from the published normative tables it consumes,
  so the derivation is auditable rather than a wall of magic numbers.
- `METHODOLOGY.md` documents this limitation prominently.

### 5.5 Composite

Inverse-variance weighted combination of whichever components have sufficient inputs:

```
composite = Σ (ageᵢ / σᵢ²) / Σ (1 / σᵢ²)
CI        = composite ± 1.96 · sqrt(1 / Σ(1/σᵢ²))      # 95% interval
```

Low-confidence weeks (per §4) additionally inflate the interval by a documented factor
before persistence, so the widening is visible in stored data and not only in the UI.

Per-component σ encodes the reference doc's reliability guidance: RHR, HRV, and step
volume dominate; the HRV component's σ is inflated for wrist-PPG noise; SpO₂ and
skin-temperature never enter as single-night values and contribute only as multi-week
trend context, not as age components.

Missing inputs degrade gracefully — no waist measurement means NTNU drops out of the
weighted sum rather than raising. If fewer than two components are available, no score is
produced for that week.

## 6. API surface

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/bioage/series?from=&to=` | Weekly points for the chart |
| GET | `/api/bioage/weeks/{week_start}` | One week's components, inputs, coverage |
| GET | `/api/daily-metrics?from=&to=` | Underlying normalized daily metrics |
| GET/PUT | `/api/profile` | Sex, birthdate |
| GET/POST/DELETE | `/api/profile/measurements` | Dated height/weight/waist rows |
| POST | `/api/sync` | Trigger ingestion (background task) |
| GET | `/api/sync/status` | Last sync, per-data-type coverage, errors |
| GET | `/api/auth/google/start` | Begin OAuth |
| GET | `/api/auth/google/callback` | OAuth redirect target |
| GET | `/api/auth/status` | Connected / token validity |

## 7. Frontend

React + TypeScript + Vite. Three pages.

**Dashboard** — the deliverable. Recharts line chart, x = ISO week, y = age in years.

- Composite biological age as a line with a shaded confidence band
- Chronological age as a reference line, making the *gap* the visual subject
- The four component estimators as individually toggleable series
- Hover tooltip: that week's component ages, input biomarker values, and data coverage
- Low-confidence weeks render as hollow markers
- A persistent methodology note linking to `METHODOLOGY.md`

**Profile** — sex and birthdate, plus dated height/weight/waist measurement rows with
add/edit/delete. The dated model is what preserves historical chart integrity.

**Connection** — OAuth connect/disconnect and status, manual sync button, last-sync
timestamp, and a per-data-type coverage table. That table doubles as the diagnostic surface
when the Air fails to populate a metric (notably `vo2-max`, which is expected empty).

Chart implementation will follow the `dataviz` skill rather than being freehanded.

## 8. Testing strategy

Test weight is deliberately concentrated on pure logic.

**Estimators** (`tests/estimators/`)
- Known-answer tests per published equation, using worked examples
- Round-trip test: NTNU at reference inputs must return chronological age
- Property tests: monotonicity — lower RHR must never increase fitness age; more steps must
  never increase step-mortality age; higher RMSSD must never increase HRV age
- KDM against synthetic reference populations constructed so the true answer is known
- Composite: weighting correctness, CI width behavior, graceful degradation with missing
  components, refusal below two components

**Parsers** (`tests/biomarkers/`)
- JSON fixtures matching documented v4 response shapes
- Empty responses, null fields, missing nights, and the expected-empty `vo2-max` case

**Client** (`tests/ingest/`)
- Mocked HTTP: pagination across `nextPageToken`, 429 backoff, token refresh on 401
- Filter expression construction per data type
- **Window chunking**: a 60-day `steps` backfill must produce five requests of ≤14 days

**Features**
- Rolling-window boundaries, missing days, median behavior with outliers
- Sleep regularity computation across midnight wraparound

**Integration** (`tests/integration/`)
- Real Postgres via pytest fixture; Alembic upgrade and downgrade
- Full mocked-API run: sync → normalize → score → API response
- Idempotency: syncing and scoring twice yields identical rows

**Frontend** — Vitest + React Testing Library on the series transform and chart components.

## 9. Demo mode

`bioage seed-demo` generates realistic synthetic history — RHR, HRV, sleep, steps with
plausible distributions, weekday/weekend structure, and gaps — so the entire application
runs end-to-end with **zero credentials**. This serves three purposes: it lets the build be
visually verified before any Google Cloud setup exists, it makes the open-source repo
immediately usable by strangers, and it provides a stable target for integration tests.

## 10. Documentation deliverables

- **`docs/SETUP.md`** — the author-facing step-by-step: create a Google Cloud project,
  enable the Google Health API, configure the OAuth consent screen (External, self added as
  a test user), add the three read scopes
  (`health_metrics_and_measurements.readonly`, `activity_and_fitness.readonly`,
  `sleep.readonly`), create a **Web application** OAuth client with redirect URI
  `http://localhost:8000/api/auth/google/callback`, download the client secret, populate
  `.env`, `docker compose up`, connect, enter profile, sync. Includes a troubleshooting
  section.
- **`docs/METHODOLOGY.md`** — every equation, every constant, every citation, and every
  caveat, including the PA-index approximation and the derived-KDM-constants limitation.
- **`README.md`** — what this is, the honest framing, quickstart via demo mode.

## 11. Known risks

| Risk | Mitigation |
|---|---|
| Google Health API shapes differ from docs | Raw JSONB store enables re-parse without re-fetch; registry isolates per-type constants |
| `filter_field` names not fully confirmed | Read from live docs at implementation; one constant per type |
| KDM reference constants are derived, not primary | Cited, flagged, script-regenerated, documented as a limitation |
| PA index mapped from steps rather than questionnaire | Documented approximation, surfaced in UI |
| Short data history (device shipped May 2026) | Coverage gating produces honest gaps rather than fabricated points |
| Wrist PPG HRV noise | Inflated σ in the composite; trend emphasized over absolute value |
