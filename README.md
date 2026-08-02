# Fitbit Air Bioage

A self-hosted app that turns the data your **Fitbit Air** syncs into **Google Health**
into a weekly biological-age estimate, tracked as a trend over time.

![Dashboard screenshot placeholder](docs/dashboard-screenshot.png)

*(screenshot to be added — run the app via the quickstart below to see it live)*

## What this is — and isn't

**This is a fitness and autonomic-nervous-system proxy, built entirely from consumer
wrist-wearable data.** It combines four independent estimators — a non-exercise fitness
age, an HRV-based age, a step-count mortality-equivalent age, and a Klemera–Doubal-style
composite biomarker age — into a single number with a confidence interval, computed
fresh each week from your resting heart rate, HRV, steps, and sleep.

**This is not a validated biological aging clock.** The gold-standard clocks in the
literature (Horvath, GrimAge, DunedinPACE from DNA methylation; Levine PhenoAge and the
original Klemera–Doubal method from blood chemistry) are trained and validated against
mortality and morbidity outcomes in large cohorts, using inputs a wrist wearable cannot
produce. Nothing here has been validated against a mortality outcome — what it reuses
from that literature is the *math*, not the underlying validated biomarker panels.

**The error bars are wide** — typically several years, roughly ±7 to ±13 at the 95%
level — and a single week's number can move for reasons that have nothing to do with
aging: a bad flu, a stressful travel week, a broken sleep schedule, a thin data window.
**The trend across many weeks is far more informative than any single value.** See
[`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) for the full accounting of every equation,
constant, and caveat.

## Quickstart (demo mode, no Google account needed)

The fastest way to see the app working is with synthetic seed data — no Google Cloud
setup required:

```bash
cp .env.example .env
docker compose up -d --build
docker compose exec backend uv run alembic upgrade head
docker compose exec backend uv run python -m bioage.cli seed-demo
```

Then open **http://localhost:5173**.

To connect your own Fitbit Air / Google Health data instead, follow
[`docs/SETUP.md`](docs/SETUP.md) — it's a step-by-step walkthrough of Google Cloud
Console for someone who's never used it before, including exact scopes, redirect URIs,
and a troubleshooting section for every error the OAuth flow can produce.

## Architecture

```
Fitbit Air (wrist)
      │  syncs over BLE
      ▼
Google Health app (phone)
      │  Google Health API v4 (OAuth 2.0, read-only)
      ▼
backend/  FastAPI + SQLAlchemy + Alembic, Python (uv-managed)
  ├─ ingest/     OAuth flow, HTTP client with retry/backoff, sync + watermarks
  ├─ biomarkers/ payload parsing, rolling-window feature computation
  ├─ estimators/ NTNU fitness age, HRV-norm age, step-count mortality age,
  │              Klemera–Doubal composite — pure functions, no I/O
  ├─ reference/  literature-sourced constants (YAML, each with a citation)
  ├─ demo/       synthetic data generator (`bioage seed-demo`)
  └─ api/        REST routes: /api/bioage/*, /api/profile, /api/auth/google/*, /api/sync
      │  JSON over HTTP
      ▼
frontend/  React + TypeScript + Vite
  ├─ pages/      Dashboard (chart), Profile (identity + measurements),
  │              Connection (OAuth + sync status + data coverage)
  └─ components/ biological-age chart with confidence band, coverage table
      │
      ▼
PostgreSQL (raw payloads, parsed daily metrics, weekly scores, profile, OAuth credentials)
```

Everything runs in Docker: `db` (Postgres), `backend` (FastAPI on :8000), `frontend`
(Vite dev server on :5173).

## Running the tests

Backend:

```bash
cd backend && uv run pytest
```

Frontend:

```bash
cd frontend && npm test
```

## Documentation

- [`docs/SETUP.md`](docs/SETUP.md) — step-by-step Google Cloud Console setup and
  troubleshooting.
- [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) — every equation, constant, citation, and
  known weakness behind the biological-age number.

## Licence

No licence file is currently included in this repository, so by default all rights are
reserved by the author. If you'd like to reuse or share this code, add a licence file
and update this section, or ask the repository owner.
