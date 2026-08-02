# Fitbit Air Biological Age Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-hosted single-user web app that pulls Fitbit Air data from the Google Health API, computes a weekly biological-age estimate from four independent estimators, and plots it against time.

**Architecture:** Four-stage backend pipeline — ingest raw JSON to Postgres, normalize to daily metrics, aggregate to 30-day rolling features, score weekly — with all scientific logic isolated as pure functions in `estimators/`. FastAPI serves a React chart. A synthetic data generator lets the whole stack run without credentials.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, Postgres 16, uv, pytest, httpx, pydantic v2, React 18, TypeScript 5, Vite, Recharts, Vitest, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-08-02-fitbit-air-bioage-design.md`

## Global Constraints

- **Python 3.12+**, dependency management via **uv** only. Never invoke `pip` directly.
- **All scientific logic in `estimators/` and `biomarkers/features.py` must be pure** — no database, network, filesystem, or clock access. They take dataclasses and return dataclasses. This is enforced by those modules importing nothing from `bioage.db`, `bioage.api`, or `bioage.ingest`.
- **Every numeric constant in `reference/*.yaml` carries a `source` citation string.** Derived constants additionally carry `derived: true`.
- **Google Health API base URL is `https://health.googleapis.com/v4`.** Not `healthapi.googleapis.com`.
- **Proto JSON encoding:** `Date` is `{"year": int, "month": int, "day": int}`; `Duration` is a string like `"28800s"`; `int64` fields arrive as **strings**. Parsers must coerce.
- **Query window caps:** `steps` = 14 days, all other data types = 90 days.
- **OAuth scopes** (exact strings):
  - `https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly`
  - `https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly`
  - `https://www.googleapis.com/auth/googlehealth.sleep.readonly`
- **No estimate is ever returned or rendered without a confidence interval.**
- Line length 100, formatted and linted with `ruff`. Type-checked with `mypy --strict` on `src/bioage/estimators/` and `src/bioage/biomarkers/`.
- Commit after every task. Conventional Commit prefixes (`feat:`, `test:`, `chore:`, `docs:`, `fix:`).

## File Structure

```
backend/
  pyproject.toml                      uv project, deps, ruff/mypy/pytest config
  alembic.ini                         Alembic config
  alembic/versions/                   migrations
  src/bioage/
    __init__.py
    config.py                         pydantic-settings; env vars
    types.py                          shared enums/dataclasses (Sex, DateRange)
    cli.py                            typer CLI: sync, rescore, seed-demo
    reference/
      __init__.py
      loader.py                       YAML → validated pydantic models
      ntnu.yaml                       HUNT coefficients + reference population
      pa_index.yaml                   steps/AZM → HUNT PA index lookup
      hrv_norms.yaml                  log-linear RMSSD-vs-age fit
      steps_mortality.yaml            Paluch dose-response knots + Gompertz MRDT
      kdm_biomarkers.yaml             per-biomarker q, k, s (derived, cited)
      composite.yaml                  per-component sigma weights
      regenerate_kdm.py               auditable script producing kdm_biomarkers.yaml
    estimators/
      __init__.py
      models.py                       EstimatorResult, BiomarkerVector dataclasses
      ntnu.py                         non-exercise VO2max → fitness age
      hrv_norm.py                     RMSSD → HRV age
      steps_mortality.py              steps → hazard → mortality-equivalent age
      kdm.py                          Klemera-Doubal estimator
      composite.py                    inverse-variance combination + CI
    biomarkers/
      __init__.py
      parsers/
        __init__.py                   PARSERS registry
        common.py                     proto-JSON coercion helpers
        daily.py                      RHR, HRV, respiratory, SpO2, temp, VO2max
        interval.py                   steps, active zone minutes
        sample.py                     weight, height
        sleep.py                      sleep session → derived metrics
      features.py                     rolling-window feature computation (pure)
      regularity.py                   circular statistics for sleep midpoint (pure)
    db/
      __init__.py
      base.py                         declarative base, session factory
      models.py                       ORM models
      repositories.py                 query helpers
    ingest/
      __init__.py
      registry.py                     DATA_TYPES registry
      client.py                       GoogleHealthClient
      oauth.py                        auth-code flow, credential persistence
      sync.py                         SyncService, watermarks
      scheduler.py                    optional APScheduler daily job
    scoring.py                        weekly scoring orchestration
    profile.py                        as-of profile resolution
    demo/
      __init__.py
      generator.py                    synthetic history generator
    api/
      __init__.py
      app.py                          FastAPI app factory
      deps.py                         DI: session, settings
      routes_bioage.py
      routes_profile.py
      routes_sync.py
      routes_auth.py
      schemas.py                      pydantic response models
  tests/
    conftest.py                       db fixture, settings fixture
    fixtures/googlehealth/*.json      captured/handwritten API payloads
    estimators/                       one test module per estimator
    biomarkers/
    ingest/
    api/
    integration/
frontend/
  package.json, tsconfig.json, vite.config.ts
  src/
    main.tsx, App.tsx
    api/client.ts, api/types.ts
    pages/Dashboard.tsx, pages/Profile.tsx, pages/Connection.tsx
    components/BioAgeChart.tsx, components/MeasurementTable.tsx,
    components/CoverageTable.tsx, components/MethodologyNote.tsx
    lib/series.ts                     API response → chart series (pure, tested)
  tests/
docker-compose.yml
.env.example
docs/SETUP.md, docs/METHODOLOGY.md
README.md
```

---

## Phase A — Foundation

### Task 1: Backend scaffold with uv and pytest

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/src/bioage/__init__.py`
- Create: `backend/src/bioage/types.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/test_types.py`
- Create: `.gitignore`

**Interfaces:**
- Consumes: nothing
- Produces: `bioage.types.Sex` (enum with `MALE`/`FEMALE`), `bioage.types.DateRange` (frozen dataclass with `start: date`, `end: date`, `.days` property, `.chunked(max_days: int) -> Iterator[DateRange]`)

- [ ] **Step 1: Write the failing test**

`backend/tests/test_types.py`:
```python
from datetime import date

import pytest

from bioage.types import DateRange, Sex


def test_sex_values():
    assert Sex.MALE.value == "male"
    assert Sex.FEMALE.value == "female"


def test_date_range_days_is_inclusive_of_start_exclusive_of_end():
    assert DateRange(date(2026, 1, 1), date(2026, 1, 15)).days == 14


def test_date_range_rejects_end_before_start():
    with pytest.raises(ValueError, match="end must be after start"):
        DateRange(date(2026, 1, 15), date(2026, 1, 1))


def test_chunked_splits_range_into_windows_no_larger_than_max():
    chunks = list(DateRange(date(2026, 1, 1), date(2026, 3, 2)).chunked(14))
    assert all(c.days <= 14 for c in chunks)
    assert chunks[0].start == date(2026, 1, 1)
    assert chunks[-1].end == date(2026, 3, 2)
    # contiguous, no gaps or overlaps
    for prev, nxt in zip(chunks, chunks[1:]):
        assert prev.end == nxt.start


def test_chunked_60_day_steps_backfill_produces_five_requests():
    chunks = list(DateRange(date(2026, 1, 1), date(2026, 3, 2)).chunked(14))
    assert len(chunks) == 5


def test_chunked_returns_single_chunk_when_range_fits():
    chunks = list(DateRange(date(2026, 1, 1), date(2026, 1, 10)).chunked(14))
    assert len(chunks) == 1
    assert chunks[0] == DateRange(date(2026, 1, 1), date(2026, 1, 10))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_types.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bioage'`

- [ ] **Step 3: Create the uv project**

`backend/pyproject.toml`:
```toml
[project]
name = "bioage"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "sqlalchemy>=2.0",
    "alembic>=1.14",
    "psycopg[binary]>=3.2",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "httpx>=0.27",
    "pyyaml>=6.0",
    "typer>=0.15",
    "google-auth>=2.35",
    "google-auth-oauthlib>=1.2",
    "apscheduler>=3.10",
    "numpy>=2.1",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "respx>=0.21",
    "ruff>=0.8",
    "mypy>=1.13",
    "types-pyyaml>=6.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/bioage"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
asyncio_mode = "auto"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[[tool.mypy.overrides]]
module = "bioage.estimators.*,bioage.biomarkers.*"
strict = true
```

`.gitignore` (repo root):
```
__pycache__/
*.py[cod]
.venv/
.env
node_modules/
dist/
.pytest_cache/
.ruff_cache/
.mypy_cache/
client_secret.json
```

- [ ] **Step 4: Implement types**

`backend/src/bioage/__init__.py`: empty file.

`backend/src/bioage/types.py`:
```python
"""Shared value types with no dependencies on any other bioage module."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum


class Sex(str, Enum):
    """Biological sex, required by the sex-stratified NTNU and HRV equations."""

    MALE = "male"
    FEMALE = "female"


@dataclass(frozen=True)
class DateRange:
    """A half-open date interval: start inclusive, end exclusive."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError("end must be after start")

    @property
    def days(self) -> int:
        return (self.end - self.start).days

    def chunked(self, max_days: int) -> Iterator[DateRange]:
        """Split into contiguous sub-ranges of at most `max_days` each.

        The Google Health API caps query ranges per data type (14 days for steps,
        90 for the rest), so any backfill longer than the cap must be issued as
        several sequential requests.
        """
        if max_days < 1:
            raise ValueError("max_days must be at least 1")
        cursor = self.start
        while cursor < self.end:
            stop = min(cursor + timedelta(days=max_days), self.end)
            yield DateRange(cursor, stop)
            cursor = stop
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_types.py -v`
Expected: PASS — 6 passed

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/src backend/tests .gitignore
git commit -m "feat: backend scaffold with uv, pytest, and shared date/sex types"
```

---

### Task 2: Configuration and Docker Compose

**Files:**
- Create: `backend/src/bioage/config.py`
- Create: `backend/tests/test_config.py`
- Create: `docker-compose.yml`
- Create: `backend/Dockerfile`
- Create: `.env.example`

**Interfaces:**
- Consumes: nothing
- Produces: `bioage.config.Settings` (pydantic-settings model) and `bioage.config.get_settings() -> Settings` (lru_cached). Fields: `database_url: str`, `google_client_id: str = ""`, `google_client_secret: str = ""`, `oauth_redirect_uri: str`, `sync_schedule_enabled: bool = False`, `sync_schedule_cron: str = "0 5 * * *"`, `backfill_days: int = 90`, `frontend_origin: str`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_config.py`:
```python
from bioage.config import Settings


def test_settings_read_from_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/bioage")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "abc.apps.googleusercontent.com")
    settings = Settings()
    assert settings.database_url == "postgresql+psycopg://u:p@db:5432/bioage"
    assert settings.google_client_id == "abc.apps.googleusercontent.com"


def test_scheduler_is_disabled_by_default(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/bioage")
    assert Settings().sync_schedule_enabled is False


def test_is_google_configured_false_when_credentials_absent(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/bioage")
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    assert Settings().is_google_configured is False


def test_is_google_configured_true_when_both_present(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/bioage")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "abc")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "shh")
    assert Settings().is_google_configured is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bioage.config'`

- [ ] **Step 3: Implement config**

`backend/src/bioage/config.py`:
```python
"""Application settings, sourced from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    google_client_id: str = ""
    google_client_secret: str = ""
    oauth_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"

    # Scheduling is opt-in so a fresh install never makes unexpected network calls.
    sync_schedule_enabled: bool = False
    sync_schedule_cron: str = "0 5 * * *"

    # How far back the first sync attempts to backfill, subject to per-data-type caps.
    backfill_days: int = 90

    frontend_origin: str = "http://localhost:5173"

    @property
    def is_google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_config.py -v`
Expected: PASS — 4 passed

- [ ] **Step 5: Write Docker Compose and Dockerfile**

`backend/Dockerfile`:
```dockerfile
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONPATH=/app/src

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY . .
RUN uv sync --frozen

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "bioage.api.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000"]
```

`docker-compose.yml` (repo root):
```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: bioage
      POSTGRES_PASSWORD: bioage
      POSTGRES_DB: bioage
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U bioage"]
      interval: 5s
      retries: 10
    ports:
      - "5432:5432"

  backend:
    build: ./backend
    env_file: .env
    environment:
      DATABASE_URL: postgresql+psycopg://bioage:bioage@db:5432/bioage
    depends_on:
      db:
        condition: service_healthy
    ports:
      - "8000:8000"
    volumes:
      - ./backend:/app

  frontend:
    image: node:22-alpine
    working_dir: /app
    command: sh -c "npm install && npm run dev -- --host 0.0.0.0"
    environment:
      VITE_API_BASE: http://localhost:8000
    volumes:
      - ./frontend:/app
    ports:
      - "5173:5173"
    depends_on:
      - backend

volumes:
  pgdata:
```

`.env.example`:
```
# Copy to .env and fill in. See docs/SETUP.md for how to obtain these.
DATABASE_URL=postgresql+psycopg://bioage:bioage@db:5432/bioage

# From Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 Client ID
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
OAUTH_REDIRECT_URI=http://localhost:8000/api/auth/google/callback

# Optional automatic daily sync (disabled by default)
SYNC_SCHEDULE_ENABLED=false
SYNC_SCHEDULE_CRON=0 5 * * *

BACKFILL_DAYS=90
FRONTEND_ORIGIN=http://localhost:5173
```

- [ ] **Step 6: Verify Postgres starts**

Run: `docker compose up -d db && docker compose exec db pg_isready -U bioage`
Expected: `/var/run/postgresql:5432 - accepting connections`

- [ ] **Step 7: Commit**

```bash
git add backend/src/bioage/config.py backend/tests/test_config.py \
        backend/Dockerfile docker-compose.yml .env.example
git commit -m "feat: settings, Docker Compose stack, and env template"
```

---

## Phase B — Pure science layer

> Everything in Phase B is a pure function. No task in this phase may import from
> `bioage.db`, `bioage.api`, or `bioage.ingest`. These tasks can be implemented and
> verified with no database running.

### Task 3: Reference constant loading

**Files:**
- Create: `backend/src/bioage/reference/__init__.py`
- Create: `backend/src/bioage/reference/loader.py`
- Create: `backend/src/bioage/reference/ntnu.yaml`
- Create: `backend/tests/estimators/__init__.py`
- Create: `backend/tests/estimators/test_reference_loader.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `bioage.reference.loader.Cited` — pydantic base with required `source: str` and `derived: bool = False`
  - `bioage.reference.loader.load_yaml(name: str) -> dict` — reads `reference/<name>.yaml`
  - `bioage.reference.loader.NtnuConstants` with `.coefficients: dict[Sex, NtnuCoefficients]` and `.reference_population: dict[Sex, NtnuReferencePopulation]`
  - `bioage.reference.loader.get_ntnu() -> NtnuConstants` (lru_cached)
  - `NtnuCoefficients` fields: `intercept, age, physical_activity, waist, resting_hr` (all float)
  - `NtnuReferencePopulation` fields: `physical_activity, waist_cm, resting_hr_bpm` (all float)

- [ ] **Step 1: Write the failing test**

`backend/tests/estimators/test_reference_loader.py`:
```python
import pytest
from pydantic import ValidationError

from bioage.reference.loader import Cited, get_ntnu, load_yaml
from bioage.types import Sex


def test_cited_requires_a_source():
    with pytest.raises(ValidationError):
        Cited()


def test_cited_accepts_source_and_defaults_derived_to_false():
    c = Cited(source="Nes et al. 2011")
    assert c.source == "Nes et al. 2011"
    assert c.derived is False


def test_load_yaml_reads_a_reference_file():
    data = load_yaml("ntnu")
    assert "coefficients" in data


def test_ntnu_male_coefficients_match_the_published_equation():
    coeff = get_ntnu().coefficients[Sex.MALE]
    assert coeff.intercept == pytest.approx(100.27)
    assert coeff.age == pytest.approx(-0.296)
    assert coeff.physical_activity == pytest.approx(0.226)
    assert coeff.waist == pytest.approx(-0.369)
    assert coeff.resting_hr == pytest.approx(-0.155)


def test_ntnu_female_coefficients_match_the_published_equation():
    coeff = get_ntnu().coefficients[Sex.FEMALE]
    assert coeff.intercept == pytest.approx(74.74)
    assert coeff.age == pytest.approx(-0.247)
    assert coeff.physical_activity == pytest.approx(0.198)
    assert coeff.waist == pytest.approx(-0.259)
    assert coeff.resting_hr == pytest.approx(-0.114)


def test_ntnu_constants_carry_a_citation():
    assert "Nes" in get_ntnu().source


def test_reference_population_defined_for_both_sexes():
    ref = get_ntnu().reference_population
    assert set(ref) == {Sex.MALE, Sex.FEMALE}
    assert ref[Sex.MALE].waist_cm > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/estimators/test_reference_loader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bioage.reference'`

- [ ] **Step 3: Write the YAML constants**

`backend/src/bioage/reference/ntnu.yaml`:
```yaml
source: >-
  Nes BM, Janszky I, Wisloff U, Stoylen A, Karlsen T. Age-predicted maximal heart rate
  in healthy subjects: The HUNT Fitness Study. Scand J Med Sci Sports 2013;23:697-704;
  non-exercise VO2max equations from the HUNT Fitness Study (n=3,320), SEE 3.5 mL/kg/min.
derived: false

coefficients:
  male:
    intercept: 100.27
    age: -0.296
    physical_activity: 0.226
    waist: -0.369
    resting_hr: -0.155
  female:
    intercept: 74.74
    age: -0.247
    physical_activity: 0.198
    waist: -0.259
    resting_hr: -0.114

# Reference population values. Fitness age is defined as the age at which a person with
# these population-typical inputs would have the subject's VO2max. Values are HUNT-cohort
# midpoints; changing them shifts all fitness ages by a constant offset, so they are
# recorded explicitly rather than hidden in code.
reference_population:
  male:
    physical_activity: 5.0
    waist_cm: 94.0
    resting_hr_bpm: 66.0
  female:
    physical_activity: 5.0
    waist_cm: 84.0
    resting_hr_bpm: 70.0
```

- [ ] **Step 4: Implement the loader**

`backend/src/bioage/reference/__init__.py`: empty file.

`backend/src/bioage/reference/loader.py`:
```python
"""Loading and validation of bundled reference constants.

Every constant used by an estimator lives in a YAML file beside this module and is
loaded through here, so that no magic numbers appear in estimator code and every value
is traceable to a citation.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from bioage.types import Sex

REFERENCE_DIR = Path(__file__).parent


class Cited(BaseModel):
    """Base for any bundled constant set: a citation is mandatory."""

    source: str = Field(min_length=1)
    derived: bool = False


def load_yaml(name: str) -> dict[str, Any]:
    path = REFERENCE_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No reference file named {name}.yaml in {REFERENCE_DIR}")
    with path.open() as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{name}.yaml must contain a mapping at the top level")
    return data


class NtnuCoefficients(BaseModel):
    intercept: float
    age: float
    physical_activity: float
    waist: float
    resting_hr: float


class NtnuReferencePopulation(BaseModel):
    physical_activity: float
    waist_cm: float
    resting_hr_bpm: float


class NtnuConstants(Cited):
    coefficients: dict[Sex, NtnuCoefficients]
    reference_population: dict[Sex, NtnuReferencePopulation]


@lru_cache
def get_ntnu() -> NtnuConstants:
    return NtnuConstants(**load_yaml("ntnu"))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/estimators/test_reference_loader.py -v`
Expected: PASS — 7 passed

- [ ] **Step 6: Commit**

```bash
git add backend/src/bioage/reference backend/tests/estimators
git commit -m "feat: cited reference-constant loader with HUNT/NTNU coefficients"
```

---

### Task 4: Estimator result types

**Files:**
- Create: `backend/src/bioage/estimators/__init__.py`
- Create: `backend/src/bioage/estimators/models.py`
- Create: `backend/tests/estimators/test_models.py`

**Interfaces:**
- Consumes: `bioage.types.Sex`
- Produces:
  - `EstimatorResult` — frozen dataclass: `component: str`, `age_years: float`, `sigma_years: float`, `inputs: dict[str, float]`. Validates `sigma_years > 0` and `0 < age_years < 130`.
  - `BiomarkerVector` — frozen dataclass of 30-day window features, all `float | None` except identity fields: `chronological_age: float`, `sex: Sex`, `resting_hr_bpm`, `hrv_rmssd_ms`, `mean_daily_steps`, `sleep_efficiency_pct`, `sleep_regularity_min`, `bmi`, `waist_cm`, `active_zone_minutes_per_day`, `respiratory_rate_brpm`.
  - `AGE_FLOOR = 18.0`, `AGE_CEILING = 100.0`, `clamp_age(value: float) -> float`

- [ ] **Step 1: Write the failing test**

`backend/tests/estimators/test_models.py`:
```python
import pytest

from bioage.estimators.models import (
    AGE_CEILING,
    AGE_FLOOR,
    BiomarkerVector,
    EstimatorResult,
    clamp_age,
)
from bioage.types import Sex


def test_result_rejects_non_positive_sigma():
    with pytest.raises(ValueError, match="sigma_years must be positive"):
        EstimatorResult(component="ntnu", age_years=40.0, sigma_years=0.0, inputs={})


def test_result_rejects_implausible_age():
    with pytest.raises(ValueError, match="age_years out of plausible range"):
        EstimatorResult(component="ntnu", age_years=500.0, sigma_years=3.0, inputs={})


def test_result_accepts_valid_values():
    r = EstimatorResult(component="ntnu", age_years=38.2, sigma_years=3.5, inputs={"rhr": 58.0})
    assert r.component == "ntnu"
    assert r.inputs["rhr"] == 58.0


def test_clamp_age_bounds_below_and_above():
    assert clamp_age(5.0) == AGE_FLOOR
    assert clamp_age(140.0) == AGE_CEILING
    assert clamp_age(42.0) == 42.0


def test_biomarker_vector_allows_missing_optional_signals():
    v = BiomarkerVector(chronological_age=40.0, sex=Sex.MALE, resting_hr_bpm=58.0)
    assert v.waist_cm is None
    assert v.hrv_rmssd_ms is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/estimators/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bioage.estimators'`

- [ ] **Step 3: Implement the models**

`backend/src/bioage/estimators/__init__.py`: empty file.

`backend/src/bioage/estimators/models.py`:
```python
"""Value types shared by every estimator.

Estimators are pure: they consume a BiomarkerVector and return an EstimatorResult.
An estimate is never expressed without an accompanying sigma, because the composite
weights components by their inverse variance and the UI must always render a band.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bioage.types import Sex

AGE_FLOOR = 18.0
AGE_CEILING = 100.0


def clamp_age(value: float) -> float:
    """Constrain an estimate to a plausible adult range.

    Extrapolating a linear equation far outside its fitting range produces numbers
    that are arithmetically valid and biologically meaningless.
    """
    return min(max(value, AGE_FLOOR), AGE_CEILING)


@dataclass(frozen=True)
class EstimatorResult:
    """One component estimate: an age, its uncertainty, and the inputs behind it."""

    component: str
    age_years: float
    sigma_years: float
    inputs: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.sigma_years <= 0:
            raise ValueError("sigma_years must be positive")
        if not 0 < self.age_years < 130:
            raise ValueError("age_years out of plausible range")


@dataclass(frozen=True)
class BiomarkerVector:
    """A 30-day rolling feature window plus subject identity.

    Every wearable-derived field is optional: coverage gaps are normal, and each
    estimator declares its own required subset.
    """

    chronological_age: float
    sex: Sex
    resting_hr_bpm: float | None = None
    hrv_rmssd_ms: float | None = None
    mean_daily_steps: float | None = None
    sleep_efficiency_pct: float | None = None
    sleep_regularity_min: float | None = None
    bmi: float | None = None
    waist_cm: float | None = None
    active_zone_minutes_per_day: float | None = None
    respiratory_rate_brpm: float | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/estimators/test_models.py -v`
Expected: PASS — 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/src/bioage/estimators backend/tests/estimators/test_models.py
git commit -m "feat: estimator result and biomarker vector value types"
```

---

### Task 5: NTNU non-exercise fitness age

**Files:**
- Create: `backend/src/bioage/reference/pa_index.yaml`
- Modify: `backend/src/bioage/reference/loader.py` (add `PaIndexConstants`, `get_pa_index()`)
- Create: `backend/src/bioage/estimators/ntnu.py`
- Create: `backend/tests/estimators/test_ntnu.py`

**Interfaces:**
- Consumes: `BiomarkerVector`, `EstimatorResult`, `clamp_age`, `get_ntnu()`
- Produces:
  - `bioage.estimators.ntnu.estimate_vo2max(age_years, sex, physical_activity, waist_cm, resting_hr_bpm) -> float`
  - `bioage.estimators.ntnu.physical_activity_index(mean_daily_steps, active_zone_minutes_per_day) -> float`
  - `bioage.estimators.ntnu.fitness_age(vector: BiomarkerVector) -> EstimatorResult | None` — returns `None` when waist or RHR is missing. Component name `"ntnu_fitness"`.

- [ ] **Step 1: Write the failing test**

`backend/tests/estimators/test_ntnu.py`:
```python
import pytest

from bioage.estimators.models import BiomarkerVector
from bioage.estimators.ntnu import estimate_vo2max, fitness_age, physical_activity_index
from bioage.reference.loader import get_ntnu
from bioage.types import Sex


def test_vo2max_male_matches_hand_computed_published_equation():
    # 100.27 - 0.296*40 + 0.226*5 - 0.369*90 - 0.155*60
    expected = 100.27 - 0.296 * 40 + 0.226 * 5 - 0.369 * 90 - 0.155 * 60
    got = estimate_vo2max(
        age_years=40, sex=Sex.MALE, physical_activity=5, waist_cm=90, resting_hr_bpm=60
    )
    assert got == pytest.approx(expected)


def test_vo2max_female_matches_hand_computed_published_equation():
    expected = 74.74 - 0.247 * 40 + 0.198 * 5 - 0.259 * 80 - 0.114 * 65
    got = estimate_vo2max(
        age_years=40, sex=Sex.FEMALE, physical_activity=5, waist_cm=80, resting_hr_bpm=65
    )
    assert got == pytest.approx(expected)


@pytest.mark.parametrize("sex", [Sex.MALE, Sex.FEMALE])
@pytest.mark.parametrize("age", [25.0, 40.0, 62.0])
def test_round_trip_reference_inputs_return_chronological_age(sex, age):
    """A subject with exactly population-typical inputs must have fitness age == real age.

    This is the definitional identity of the estimator; if it fails, the inversion is
    inconsistent with the forward equation.
    """
    ref = get_ntnu().reference_population[sex]
    vector = BiomarkerVector(
        chronological_age=age,
        sex=sex,
        resting_hr_bpm=ref.resting_hr_bpm,
        waist_cm=ref.waist_cm,
        mean_daily_steps=None,
        active_zone_minutes_per_day=None,
    )
    result = fitness_age(vector, physical_activity_override=ref.physical_activity)
    assert result is not None
    assert result.age_years == pytest.approx(age, abs=1e-9)


def test_lower_resting_hr_never_increases_fitness_age():
    def age_for(rhr: float) -> float:
        v = BiomarkerVector(
            chronological_age=40.0, sex=Sex.MALE, resting_hr_bpm=rhr,
            waist_cm=90.0, mean_daily_steps=8000.0,
        )
        result = fitness_age(v)
        assert result is not None
        return result.age_years

    assert age_for(50.0) <= age_for(60.0) <= age_for(75.0)


def test_larger_waist_never_decreases_fitness_age():
    def age_for(waist: float) -> float:
        v = BiomarkerVector(
            chronological_age=40.0, sex=Sex.MALE, resting_hr_bpm=60.0,
            waist_cm=waist, mean_daily_steps=8000.0,
        )
        result = fitness_age(v)
        assert result is not None
        return result.age_years

    assert age_for(80.0) <= age_for(95.0) <= age_for(110.0)


def test_returns_none_when_waist_missing():
    v = BiomarkerVector(chronological_age=40.0, sex=Sex.MALE, resting_hr_bpm=60.0)
    assert fitness_age(v) is None


def test_returns_none_when_resting_hr_missing():
    v = BiomarkerVector(chronological_age=40.0, sex=Sex.MALE, waist_cm=90.0)
    assert fitness_age(v) is None


def test_physical_activity_index_is_monotonic_in_steps():
    a = physical_activity_index(3000, 0)
    b = physical_activity_index(8000, 0)
    c = physical_activity_index(15000, 0)
    assert a < b < c


def test_physical_activity_index_is_bounded():
    assert 0.0 <= physical_activity_index(0, 0) <= 15.0
    assert 0.0 <= physical_activity_index(40000, 300) <= 15.0


def test_physical_activity_index_falls_back_to_reference_when_no_data():
    v = BiomarkerVector(
        chronological_age=40.0, sex=Sex.MALE, resting_hr_bpm=60.0, waist_cm=90.0
    )
    result = fitness_age(v)
    assert result is not None
    assert result.inputs["physical_activity"] == pytest.approx(5.0)


def test_result_reports_its_inputs_and_sigma():
    v = BiomarkerVector(
        chronological_age=40.0, sex=Sex.MALE, resting_hr_bpm=58.0,
        waist_cm=88.0, mean_daily_steps=10000.0,
    )
    result = fitness_age(v)
    assert result is not None
    assert result.component == "ntnu_fitness"
    assert result.sigma_years > 0
    assert set(result.inputs) >= {"resting_hr_bpm", "waist_cm", "physical_activity", "vo2max"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/estimators/test_ntnu.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bioage.estimators.ntnu'`

- [ ] **Step 3: Write the PA index YAML**

`backend/src/bioage/reference/pa_index.yaml`:
```yaml
source: >-
  APPROXIMATION. The HUNT physical activity index is a questionnaire score combining
  frequency, duration and intensity of exercise (Nes et al. 2011). No published mapping
  from step counts to that index exists. These knots were chosen so that sedentary
  (<4,000 steps/day) maps near the bottom of the scale, the population-typical 7,000-8,000
  steps/day maps to the reference value of 5.0 used in ntnu.yaml, and highly active
  (>15,000 steps/day) approaches the ceiling. Active Zone Minutes add an intensity bonus
  because the HUNT index weights intensity, which steps alone cannot express.
derived: true

# Piecewise-linear knots: mean daily steps -> base index
steps_knots:
  - [0, 0.0]
  - [2000, 1.0]
  - [4000, 2.5]
  - [6000, 4.0]
  - [7500, 5.0]
  - [10000, 6.5]
  - [12500, 7.5]
  - [15000, 8.5]
  - [20000, 10.0]

# Intensity bonus: mean daily Active Zone Minutes -> index added to the base
azm_knots:
  - [0, 0.0]
  - [10, 0.5]
  - [22, 1.5]
  - [45, 3.0]
  - [90, 4.5]

index_ceiling: 15.0

# Used when neither steps nor AZM are available for the window.
fallback_index: 5.0

# Standard error of the resulting fitness age, in years. The HUNT VO2max equation has
# SEE 3.5 mL/kg/min; dividing by the male age coefficient (0.296 mL/kg/min per year)
# gives ~11.8 years, which is then treated as a 2-sigma spread.
fitness_age_sigma_years: 5.9
```

- [ ] **Step 4: Extend the loader**

Append to `backend/src/bioage/reference/loader.py`:
```python
class PaIndexConstants(Cited):
    steps_knots: list[tuple[float, float]]
    azm_knots: list[tuple[float, float]]
    index_ceiling: float
    fallback_index: float
    fitness_age_sigma_years: float


@lru_cache
def get_pa_index() -> PaIndexConstants:
    return PaIndexConstants(**load_yaml("pa_index"))
```

- [ ] **Step 5: Implement the estimator**

`backend/src/bioage/estimators/ntnu.py`:
```python
"""Non-exercise fitness age from the HUNT Fitness Study VO2max equations.

The Fitbit Air produces no usable VO2max (Google derives it only from GPS-tracked runs),
so this estimator uses the non-exercise form, which needs only age, sex, waist
circumference, resting heart rate and a physical-activity index.

Fitness age is defined by inverting the same equation at population-typical activity,
waist and resting HR: it is the age at which a typical person would have the subject's
estimated VO2max. Using one equation in both directions guarantees the round-trip
identity `fitness_age(vo2max(age, reference inputs)) == age`.
"""

from __future__ import annotations

from bioage.estimators.models import BiomarkerVector, EstimatorResult, clamp_age
from bioage.reference.loader import get_ntnu, get_pa_index
from bioage.types import Sex

COMPONENT = "ntnu_fitness"


def _interpolate(knots: list[tuple[float, float]], x: float) -> float:
    """Piecewise-linear interpolation, clamped at both ends."""
    if x <= knots[0][0]:
        return knots[0][1]
    if x >= knots[-1][0]:
        return knots[-1][1]
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        if x0 <= x <= x1:
            span = x1 - x0
            return y0 if span == 0 else y0 + (y1 - y0) * (x - x0) / span
    return knots[-1][1]


def physical_activity_index(
    mean_daily_steps: float | None,
    active_zone_minutes_per_day: float | None,
) -> float:
    """Approximate the HUNT questionnaire activity index from wearable activity.

    This is the weakest input in the estimator; see reference/pa_index.yaml.
    """
    constants = get_pa_index()
    base = _interpolate(constants.steps_knots, mean_daily_steps or 0.0)
    bonus = _interpolate(constants.azm_knots, active_zone_minutes_per_day or 0.0)
    return min(base + bonus, constants.index_ceiling)


def estimate_vo2max(
    *,
    age_years: float,
    sex: Sex,
    physical_activity: float,
    waist_cm: float,
    resting_hr_bpm: float,
) -> float:
    """Non-exercise VO2max estimate in mL/kg/min."""
    c = get_ntnu().coefficients[sex]
    return (
        c.intercept
        + c.age * age_years
        + c.physical_activity * physical_activity
        + c.waist * waist_cm
        + c.resting_hr * resting_hr_bpm
    )


def fitness_age(
    vector: BiomarkerVector,
    physical_activity_override: float | None = None,
) -> EstimatorResult | None:
    """Return the NTNU fitness age, or None if required inputs are unavailable."""
    if vector.waist_cm is None or vector.resting_hr_bpm is None:
        return None

    constants = get_ntnu()
    coeff = constants.coefficients[vector.sex]
    reference = constants.reference_population[vector.sex]

    if physical_activity_override is not None:
        activity = physical_activity_override
    elif vector.mean_daily_steps is None and vector.active_zone_minutes_per_day is None:
        activity = get_pa_index().fallback_index
    else:
        activity = physical_activity_index(
            vector.mean_daily_steps, vector.active_zone_minutes_per_day
        )

    vo2max = estimate_vo2max(
        age_years=vector.chronological_age,
        sex=vector.sex,
        physical_activity=activity,
        waist_cm=vector.waist_cm,
        resting_hr_bpm=vector.resting_hr_bpm,
    )

    # Invert the same equation at reference inputs and solve for age.
    # vo2max = intercept + age*A + pa*PA_ref + waist*WC_ref + rhr*RHR_ref
    baseline = (
        coeff.intercept
        + coeff.physical_activity * reference.physical_activity
        + coeff.waist * reference.waist_cm
        + coeff.resting_hr * reference.resting_hr_bpm
    )
    age = (vo2max - baseline) / coeff.age  # coeff.age is negative

    return EstimatorResult(
        component=COMPONENT,
        age_years=clamp_age(age),
        sigma_years=get_pa_index().fitness_age_sigma_years,
        inputs={
            "resting_hr_bpm": vector.resting_hr_bpm,
            "waist_cm": vector.waist_cm,
            "physical_activity": activity,
            "vo2max": vo2max,
        },
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/estimators/test_ntnu.py -v`
Expected: PASS — 15 passed (the round-trip test is parametrized 6 ways)

- [ ] **Step 7: Commit**

```bash
git add backend/src/bioage/estimators/ntnu.py backend/src/bioage/reference/pa_index.yaml \
        backend/src/bioage/reference/loader.py backend/tests/estimators/test_ntnu.py
git commit -m "feat: NTNU non-exercise fitness age estimator with round-trip identity test"
```

---

### Task 6: HRV-norm age

**Files:**
- Create: `backend/src/bioage/reference/hrv_norms.yaml`
- Modify: `backend/src/bioage/reference/loader.py` (add `HrvNormConstants`, `get_hrv_norms()`)
- Create: `backend/src/bioage/estimators/hrv_norm.py`
- Create: `backend/tests/estimators/test_hrv_norm.py`

**Interfaces:**
- Consumes: `BiomarkerVector`, `EstimatorResult`, `clamp_age`
- Produces:
  - `bioage.estimators.hrv_norm.expected_rmssd(age_years: float, sex: Sex) -> float`
  - `bioage.estimators.hrv_norm.hrv_age(vector: BiomarkerVector) -> EstimatorResult | None` — `None` when `hrv_rmssd_ms` missing. Component `"hrv_norm"`.

- [ ] **Step 1: Write the failing test**

`backend/tests/estimators/test_hrv_norm.py`:
```python
import pytest

from bioage.estimators.hrv_norm import expected_rmssd, hrv_age
from bioage.estimators.models import BiomarkerVector
from bioage.types import Sex


@pytest.mark.parametrize(
    ("age", "approx_rmssd"),
    [(25.0, 60.0), (45.0, 43.0), (55.0, 34.0), (65.0, 31.0)],
)
def test_expected_rmssd_tracks_published_normative_medians(age, approx_rmssd):
    """The fitted curve must stay close to the normative medians it was fitted to."""
    assert expected_rmssd(age, Sex.MALE) == pytest.approx(approx_rmssd, rel=0.15)


def test_expected_rmssd_declines_monotonically_with_age():
    values = [expected_rmssd(a, Sex.MALE) for a in range(20, 80, 5)]
    assert values == sorted(values, reverse=True)


@pytest.mark.parametrize("age", [30.0, 45.0, 60.0])
def test_round_trip_normative_rmssd_returns_that_age(age):
    """Feeding the norm for an age back in must recover that age."""
    v = BiomarkerVector(
        chronological_age=age, sex=Sex.MALE, hrv_rmssd_ms=expected_rmssd(age, Sex.MALE)
    )
    result = hrv_age(v)
    assert result is not None
    assert result.age_years == pytest.approx(age, abs=1e-6)


def test_higher_rmssd_never_increases_hrv_age():
    def age_for(rmssd: float) -> float:
        result = hrv_age(
            BiomarkerVector(chronological_age=40.0, sex=Sex.MALE, hrv_rmssd_ms=rmssd)
        )
        assert result is not None
        return result.age_years

    assert age_for(70.0) <= age_for(45.0) <= age_for(25.0)


def test_returns_none_when_rmssd_missing():
    assert hrv_age(BiomarkerVector(chronological_age=40.0, sex=Sex.MALE)) is None


def test_rejects_non_positive_rmssd():
    v = BiomarkerVector(chronological_age=40.0, sex=Sex.MALE, hrv_rmssd_ms=0.0)
    assert hrv_age(v) is None


def test_extreme_rmssd_is_clamped_not_extrapolated_absurdly():
    v = BiomarkerVector(chronological_age=40.0, sex=Sex.MALE, hrv_rmssd_ms=400.0)
    result = hrv_age(v)
    assert result is not None
    assert 18.0 <= result.age_years <= 100.0


def test_sigma_reflects_wrist_ppg_noise_and_exceeds_ntnu_precision():
    v = BiomarkerVector(chronological_age=40.0, sex=Sex.MALE, hrv_rmssd_ms=45.0)
    result = hrv_age(v)
    assert result is not None
    assert result.sigma_years >= 6.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/estimators/test_hrv_norm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bioage.estimators.hrv_norm'`

- [ ] **Step 3: Write the HRV norms YAML**

`backend/src/bioage/reference/hrv_norms.yaml`:
```yaml
source: >-
  DERIVED. Log-linear fit through nightly RMSSD normative medians reported in
  reference-research-from-claude.md (approx. 60 ms at 25y, 43 ms in the 40s, 34 ms in the
  50s, 31 ms in the 60s), consistent with the widely reported 1-3%/year decline in RMSSD
  after the mid-20s. Coefficients satisfy ln(RMSSD) = intercept + slope * age.
  Female offset reflects the small sex difference in RMSSD reported in normative studies
  and is applied as a multiplicative factor on the fitted curve.
derived: true

male:
  ln_intercept: 4.5326
  ln_slope: -0.01614
female:
  ln_intercept: 4.5626
  ln_slope: -0.01614

# Nightly wrist-PPG RMSSD carries MAPE frequently above 10% against ECG reference
# (Dial et al. 2025). Propagating a 12% measurement error through the fitted slope
# (0.01614 per year in log space) gives roughly 7 years.
sigma_years: 7.0

min_rmssd_ms: 5.0
max_rmssd_ms: 250.0
```

- [ ] **Step 4: Extend the loader**

Append to `backend/src/bioage/reference/loader.py`:
```python
class HrvSexFit(BaseModel):
    ln_intercept: float
    ln_slope: float


class HrvNormConstants(Cited):
    male: HrvSexFit
    female: HrvSexFit
    sigma_years: float
    min_rmssd_ms: float
    max_rmssd_ms: float

    def fit_for(self, sex: Sex) -> HrvSexFit:
        return self.male if sex is Sex.MALE else self.female


@lru_cache
def get_hrv_norms() -> HrvNormConstants:
    return HrvNormConstants(**load_yaml("hrv_norms"))
```

- [ ] **Step 5: Implement the estimator**

`backend/src/bioage/estimators/hrv_norm.py`:
```python
"""HRV age: invert nightly RMSSD against age/sex normative medians.

RMSSD declines roughly log-linearly with age after the mid-20s. Fitting
ln(RMSSD) = a + b*age lets the estimate be inverted in closed form:
    age = (ln(RMSSD) - a) / b

Fitbit computes HRV only during sleep, and consumer wrist PPG HRV is materially noisier
than ECG, so this component carries a deliberately wide sigma.
"""

from __future__ import annotations

import math

from bioage.estimators.models import BiomarkerVector, EstimatorResult, clamp_age
from bioage.reference.loader import get_hrv_norms
from bioage.types import Sex

COMPONENT = "hrv_norm"


def expected_rmssd(age_years: float, sex: Sex) -> float:
    """Normative nightly RMSSD in milliseconds for a given age and sex."""
    fit = get_hrv_norms().fit_for(sex)
    return math.exp(fit.ln_intercept + fit.ln_slope * age_years)


def hrv_age(vector: BiomarkerVector) -> EstimatorResult | None:
    """Return the HRV-norm age, or None if RMSSD is unavailable or implausible."""
    rmssd = vector.hrv_rmssd_ms
    constants = get_hrv_norms()
    if rmssd is None or rmssd <= 0:
        return None

    bounded = min(max(rmssd, constants.min_rmssd_ms), constants.max_rmssd_ms)
    fit = constants.fit_for(vector.sex)
    age = (math.log(bounded) - fit.ln_intercept) / fit.ln_slope

    return EstimatorResult(
        component=COMPONENT,
        age_years=clamp_age(age),
        sigma_years=constants.sigma_years,
        inputs={
            "hrv_rmssd_ms": rmssd,
            "expected_rmssd_ms": expected_rmssd(vector.chronological_age, vector.sex),
        },
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/estimators/test_hrv_norm.py -v`
Expected: PASS — 14 passed

- [ ] **Step 7: Verify the fitted curve actually matches the norms**

Run:
```bash
cd backend && uv run python -c "
from bioage.estimators.hrv_norm import expected_rmssd
from bioage.types import Sex
for a in (25, 45, 55, 65):
    print(a, round(expected_rmssd(a, Sex.MALE), 1))
"
```
Expected: values close to 60, 43, 34, 31 (within 15%). If not, re-fit `ln_intercept`/`ln_slope` by least squares on the four normative points and update the YAML.

- [ ] **Step 8: Commit**

```bash
git add backend/src/bioage/estimators/hrv_norm.py backend/src/bioage/reference/hrv_norms.yaml \
        backend/src/bioage/reference/loader.py backend/tests/estimators/test_hrv_norm.py
git commit -m "feat: HRV-norm age estimator from log-linear RMSSD decline"
```

---

### Task 7: Step-count mortality-equivalent age

**Files:**
- Create: `backend/src/bioage/reference/steps_mortality.yaml`
- Modify: `backend/src/bioage/reference/loader.py` (add `StepsMortalityConstants`, `get_steps_mortality()`)
- Create: `backend/src/bioage/estimators/steps_mortality.py`
- Create: `backend/tests/estimators/test_steps_mortality.py`

**Interfaces:**
- Consumes: `BiomarkerVector`, `EstimatorResult`, `clamp_age`
- Produces:
  - `bioage.estimators.steps_mortality.hazard_ratio(mean_daily_steps: float) -> float`
  - `bioage.estimators.steps_mortality.steps_age(vector: BiomarkerVector) -> EstimatorResult | None` — `None` when `mean_daily_steps` missing. Component `"steps_mortality"`.

- [ ] **Step 1: Write the failing test**

`backend/tests/estimators/test_steps_mortality.py`:
```python
import pytest

from bioage.estimators.models import BiomarkerVector
from bioage.estimators.steps_mortality import hazard_ratio, steps_age
from bioage.types import Sex


def test_reference_step_count_has_hazard_ratio_of_one():
    from bioage.reference.loader import get_steps_mortality

    assert hazard_ratio(get_steps_mortality().reference_steps) == pytest.approx(1.0)


def test_hazard_ratio_decreases_with_more_steps():
    assert hazard_ratio(2000) > hazard_ratio(6000) > hazard_ratio(10000)


def test_hazard_ratio_plateaus_at_high_step_counts():
    """Paluch reports the benefit levelling off; beyond the plateau nothing should change."""
    assert hazard_ratio(16000) == pytest.approx(hazard_ratio(25000))


def test_hazard_ratio_stays_positive():
    assert hazard_ratio(0) > 0
    assert hazard_ratio(100000) > 0


def test_age_equals_chronological_age_at_reference_steps():
    from bioage.reference.loader import get_steps_mortality

    v = BiomarkerVector(
        chronological_age=45.0,
        sex=Sex.MALE,
        mean_daily_steps=get_steps_mortality().reference_steps,
    )
    result = steps_age(v)
    assert result is not None
    assert result.age_years == pytest.approx(45.0)


def test_halving_hazard_subtracts_one_mortality_rate_doubling_time():
    """Gompertz: hazard doubles every MRDT years, so HR=0.5 is one MRDT younger."""
    from bioage.reference.loader import get_steps_mortality

    constants = get_steps_mortality()
    # Find a step count whose hazard ratio is 0.5 by bisection.
    lo, hi = constants.reference_steps, 100000.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if hazard_ratio(mid) > 0.5:
            lo = mid
        else:
            hi = mid
    if hazard_ratio(lo) > 0.5 and hazard_ratio(hi) > 0.5:
        pytest.skip("dose-response curve never reaches HR 0.5")
    v = BiomarkerVector(chronological_age=50.0, sex=Sex.MALE, mean_daily_steps=hi)
    result = steps_age(v)
    assert result is not None
    assert result.age_years == pytest.approx(50.0 - constants.mrdt_years, abs=0.5)


def test_more_steps_never_increases_age():
    def age_for(steps: float) -> float:
        result = steps_age(
            BiomarkerVector(chronological_age=50.0, sex=Sex.MALE, mean_daily_steps=steps)
        )
        assert result is not None
        return result.age_years

    assert age_for(15000) <= age_for(8000) <= age_for(3000)


def test_returns_none_when_steps_missing():
    assert steps_age(BiomarkerVector(chronological_age=40.0, sex=Sex.MALE)) is None


def test_result_is_clamped_to_plausible_range():
    v = BiomarkerVector(chronological_age=20.0, sex=Sex.MALE, mean_daily_steps=30000.0)
    result = steps_age(v)
    assert result is not None
    assert result.age_years >= 18.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/estimators/test_steps_mortality.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bioage.estimators.steps_mortality'`

- [ ] **Step 3: Write the steps-mortality YAML**

`backend/src/bioage/reference/steps_mortality.yaml`:
```yaml
source: >-
  Paluch AE, Bajpai S, Bassett DR, et al. Daily steps and all-cause mortality: a
  meta-analysis of 15 international cohorts. Lancet Public Health 2022;7(3):e219-e228
  (47,471 adults, 3,013 deaths). Hazard ratios are relative to the lowest-quartile
  referent; the knots below are digitised from the reported dose-response, rescaled so
  that reference_steps has HR 1.0. The benefit plateaus between roughly 6,000-10,000
  steps/day in older adults and 8,000-10,000 in younger adults; a single plateau at
  14,000 is used here as a conservative simplification.
derived: true

reference_steps: 7500.0

# mean daily steps -> all-cause mortality hazard ratio, relative to reference_steps
hazard_knots:
  - [0, 1.70]
  - [2000, 1.52]
  - [4000, 1.26]
  - [6000, 1.09]
  - [7500, 1.00]
  - [9000, 0.94]
  - [10000, 0.90]
  - [12000, 0.86]
  - [14000, 0.84]

# Gompertz mortality rate doubling time in adults, used to convert a hazard ratio into
# an age offset: age_offset = ln(HR) / ln(2) * mrdt_years.
mrdt_years: 8.0

sigma_years: 8.0
```

- [ ] **Step 4: Extend the loader**

Append to `backend/src/bioage/reference/loader.py`:
```python
class StepsMortalityConstants(Cited):
    reference_steps: float
    hazard_knots: list[tuple[float, float]]
    mrdt_years: float
    sigma_years: float


@lru_cache
def get_steps_mortality() -> StepsMortalityConstants:
    return StepsMortalityConstants(**load_yaml("steps_mortality"))
```

- [ ] **Step 5: Implement the estimator**

`backend/src/bioage/estimators/steps_mortality.py`:
```python
"""Mortality-equivalent age from daily step volume.

Two published results are composed:

1. Paluch et al. 2022 give an all-cause mortality hazard ratio as a function of mean
   daily steps, plateauing at high step counts.
2. The Gompertz law states adult mortality hazard doubles roughly every 8 years.

Together: a hazard ratio HR corresponds to an age offset of ln(HR)/ln(2) * MRDT years.
A person walking the reference step count sits exactly at their chronological age.
"""

from __future__ import annotations

import math

from bioage.estimators.models import BiomarkerVector, EstimatorResult, clamp_age
from bioage.reference.loader import get_steps_mortality

COMPONENT = "steps_mortality"


def _interpolate(knots: list[tuple[float, float]], x: float) -> float:
    if x <= knots[0][0]:
        return knots[0][1]
    if x >= knots[-1][0]:
        return knots[-1][1]
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        if x0 <= x <= x1:
            span = x1 - x0
            return y0 if span == 0 else y0 + (y1 - y0) * (x - x0) / span
    return knots[-1][1]


def hazard_ratio(mean_daily_steps: float) -> float:
    """All-cause mortality hazard ratio relative to the reference step count."""
    return _interpolate(get_steps_mortality().hazard_knots, max(mean_daily_steps, 0.0))


def steps_age(vector: BiomarkerVector) -> EstimatorResult | None:
    """Return the step-count mortality-equivalent age, or None if steps are missing."""
    steps = vector.mean_daily_steps
    if steps is None:
        return None

    constants = get_steps_mortality()
    ratio = hazard_ratio(steps)
    offset = math.log(ratio) / math.log(2.0) * constants.mrdt_years
    age = vector.chronological_age + offset

    return EstimatorResult(
        component=COMPONENT,
        age_years=clamp_age(age),
        sigma_years=constants.sigma_years,
        inputs={"mean_daily_steps": steps, "hazard_ratio": ratio, "age_offset": offset},
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/estimators/test_steps_mortality.py -v`
Expected: PASS — 9 passed (one may skip if the curve never reaches HR 0.5)

- [ ] **Step 7: Commit**

```bash
git add backend/src/bioage/estimators/steps_mortality.py \
        backend/src/bioage/reference/steps_mortality.yaml \
        backend/src/bioage/reference/loader.py \
        backend/tests/estimators/test_steps_mortality.py
git commit -m "feat: step-count mortality-equivalent age via Paluch dose-response and Gompertz"
```

---

### Task 8: Klemera–Doubal estimator

**Files:**
- Create: `backend/src/bioage/reference/kdm_biomarkers.yaml`
- Create: `backend/src/bioage/reference/regenerate_kdm.py`
- Modify: `backend/src/bioage/reference/loader.py` (add `KdmConstants`, `get_kdm()`)
- Create: `backend/src/bioage/estimators/kdm.py`
- Create: `backend/tests/estimators/test_kdm.py`

**Interfaces:**
- Consumes: `BiomarkerVector`, `EstimatorResult`, `clamp_age`, `Sex`
- Produces:
  - `bioage.estimators.kdm.BiomarkerReference` — frozen dataclass: `name: str`, `q: float`, `k: float`, `s: float`
  - `bioage.estimators.kdm.kdm_bio_age(observations: dict[str, float], references: dict[str, BiomarkerReference], chronological_age: float, s_ba: float | None) -> float`
  - `bioage.estimators.kdm.kdm_age(vector: BiomarkerVector) -> EstimatorResult | None` — `None` when fewer than `min_biomarkers` are present. Component `"kdm"`.

> **Formula.** `BA_E = Σⱼ[(xⱼ−qⱼ)·kⱼ/sⱼ²] / Σⱼ[kⱼ²/sⱼ²]`, and with the chronological-age
> correction `BA_EC = [Σⱼ((xⱼ−qⱼ)kⱼ/sⱼ²) + CA/s²_BA] / [Σⱼ(kⱼ²/sⱼ²) + 1/s²_BA]`.
> Note the denominator squares `kⱼ`, **not** `kⱼ/sⱼ²`. The version printed in
> `reference-research-from-claude.md` is wrong and does not satisfy the identity tested
> in Step 1.

- [ ] **Step 1: Write the failing test**

`backend/tests/estimators/test_kdm.py`:
```python
import pytest

from bioage.estimators.kdm import BiomarkerReference, kdm_age, kdm_bio_age
from bioage.estimators.models import BiomarkerVector
from bioage.types import Sex

REFS = {
    "a": BiomarkerReference(name="a", q=50.0, k=0.30, s=6.0),
    "b": BiomarkerReference(name="b", q=20.0, k=-0.20, s=4.0),
    "c": BiomarkerReference(name="c", q=90.0, k=0.10, s=2.0),
}


def _on_the_line(age: float) -> dict[str, float]:
    """Observations lying exactly on each biomarker's reference regression."""
    return {name: ref.q + ref.k * age for name, ref in REFS.items()}


@pytest.mark.parametrize("age", [25.0, 40.0, 55.0, 70.0])
def test_subject_on_the_reference_regression_recovers_that_age(age):
    """The defining identity of KDM.

    If x_j = q_j + k_j*A for every biomarker, the estimator must return exactly A.
    This is the test that distinguishes the correct denominator (sum k^2/s^2) from the
    incorrect one (sum (k/s^2)^2) quoted in the source research document.
    """
    result = kdm_bio_age(_on_the_line(age), REFS, chronological_age=age, s_ba=None)
    assert result == pytest.approx(age, abs=1e-9)


def test_identity_holds_regardless_of_chronological_age_when_uncorrected():
    """Without the correction term, chronological age must not influence the result."""
    a = kdm_bio_age(_on_the_line(40.0), REFS, chronological_age=20.0, s_ba=None)
    b = kdm_bio_age(_on_the_line(40.0), REFS, chronological_age=80.0, s_ba=None)
    assert a == pytest.approx(b)


def test_correction_shrinks_estimate_toward_chronological_age():
    uncorrected = kdm_bio_age(_on_the_line(60.0), REFS, chronological_age=40.0, s_ba=None)
    corrected = kdm_bio_age(_on_the_line(60.0), REFS, chronological_age=40.0, s_ba=10.0)
    assert 40.0 < corrected < uncorrected


def test_smaller_s_ba_shrinks_harder():
    weak = kdm_bio_age(_on_the_line(60.0), REFS, chronological_age=40.0, s_ba=30.0)
    strong = kdm_bio_age(_on_the_line(60.0), REFS, chronological_age=40.0, s_ba=3.0)
    assert abs(strong - 40.0) < abs(weak - 40.0)


def test_biomarker_with_larger_residual_sd_has_less_influence():
    """Doubling s halves the weight k/s^2 twice over; the noisy marker should matter less."""
    noisy = {
        "a": BiomarkerReference(name="a", q=50.0, k=0.30, s=6.0),
        "b": BiomarkerReference(name="b", q=20.0, k=-0.20, s=40.0),
    }
    tight = {
        "a": BiomarkerReference(name="a", q=50.0, k=0.30, s=6.0),
        "b": BiomarkerReference(name="b", q=20.0, k=-0.20, s=4.0),
    }
    # 'a' says 60, 'b' says 30.
    obs = {"a": 50.0 + 0.30 * 60.0, "b": 20.0 - 0.20 * 30.0}
    with_noisy_b = kdm_bio_age(obs, noisy, chronological_age=45.0, s_ba=None)
    with_tight_b = kdm_bio_age(obs, tight, chronological_age=45.0, s_ba=None)
    assert abs(with_noisy_b - 60.0) < abs(with_tight_b - 60.0)


def test_ignores_observations_with_no_reference():
    a = kdm_bio_age(_on_the_line(50.0), REFS, chronological_age=50.0, s_ba=None)
    obs = _on_the_line(50.0) | {"unknown_marker": 12345.0}
    b = kdm_bio_age(obs, REFS, chronological_age=50.0, s_ba=None)
    assert a == pytest.approx(b)


def test_raises_when_no_biomarkers_overlap_the_references():
    with pytest.raises(ValueError, match="no biomarkers"):
        kdm_bio_age({"zzz": 1.0}, REFS, chronological_age=50.0, s_ba=None)


def test_rejects_zero_residual_sd():
    with pytest.raises(ValueError, match="s must be positive"):
        BiomarkerReference(name="bad", q=1.0, k=1.0, s=0.0)


def test_rejects_zero_slope():
    """A biomarker that does not change with age carries no age information."""
    with pytest.raises(ValueError, match="k must be non-zero"):
        BiomarkerReference(name="flat", q=1.0, k=0.0, s=1.0)


def test_kdm_age_returns_none_with_too_few_biomarkers():
    v = BiomarkerVector(chronological_age=40.0, sex=Sex.MALE, resting_hr_bpm=60.0)
    assert kdm_age(v) is None


def test_kdm_age_produces_result_with_enough_biomarkers():
    v = BiomarkerVector(
        chronological_age=40.0,
        sex=Sex.MALE,
        resting_hr_bpm=60.0,
        hrv_rmssd_ms=45.0,
        mean_daily_steps=9000.0,
        sleep_efficiency_pct=90.0,
        bmi=23.5,
    )
    result = kdm_age(v)
    assert result is not None
    assert result.component == "kdm"
    assert 18.0 <= result.age_years <= 100.0
    assert result.sigma_years > 0


def test_kdm_age_worsening_every_biomarker_increases_the_estimate():
    healthy = BiomarkerVector(
        chronological_age=40.0, sex=Sex.MALE, resting_hr_bpm=52.0, hrv_rmssd_ms=65.0,
        mean_daily_steps=13000.0, sleep_efficiency_pct=94.0, bmi=22.0,
    )
    unhealthy = BiomarkerVector(
        chronological_age=40.0, sex=Sex.MALE, resting_hr_bpm=78.0, hrv_rmssd_ms=22.0,
        mean_daily_steps=2500.0, sleep_efficiency_pct=76.0, bmi=32.0,
    )
    good, bad = kdm_age(healthy), kdm_age(unhealthy)
    assert good is not None and bad is not None
    assert good.age_years < bad.age_years
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/estimators/test_kdm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bioage.estimators.kdm'`

- [ ] **Step 3: Write the regeneration script**

`backend/src/bioage/reference/regenerate_kdm.py`:
```python
"""Regenerate kdm_biomarkers.yaml from published age-stratified normative tables.

Run with:  uv run python -m bioage.reference.regenerate_kdm

No published NHANES table gives Klemera-Doubal q/k/s parameters for wearable-derived
biomarkers. This script derives them by ordinary least squares on the normative
age-stratum means below, taking the residual SD as the pooled within-stratum SD.
Keeping the derivation in source form is what makes the resulting constants auditable
rather than magic numbers.

Each NORMS entry is (age midpoint, mean value, within-stratum SD).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import yaml

NORMS: dict[str, dict[str, object]] = {
    "resting_hr_bpm": {
        "source": (
            "Resting heart rate rises modestly with age in adults; strata approximate "
            "NHANES adult resting pulse distributions (Ostchega et al., NCHS Data Brief)."
        ),
        "points": [(25.0, 66.0, 9.5), (35.0, 67.0, 9.5), (45.0, 68.5, 9.8),
                   (55.0, 69.5, 10.0), (65.0, 70.5, 10.2), (75.0, 71.5, 10.5)],
    },
    "hrv_rmssd_ms": {
        "source": (
            "Nightly RMSSD normative medians from reference-research-from-claude.md, "
            "consistent with a 1-3%/year decline after the mid-20s."
        ),
        "points": [(25.0, 60.0, 22.0), (35.0, 50.0, 19.0), (45.0, 43.0, 16.0),
                   (55.0, 34.0, 13.0), (65.0, 31.0, 12.0), (75.0, 28.0, 11.0)],
    },
    "mean_daily_steps": {
        "source": (
            "Age-stratified mean daily step counts decline steadily through adulthood "
            "(Althoff et al., Nature 2017; NHANES accelerometry summaries)."
        ),
        "points": [(25.0, 9500.0, 3800.0), (35.0, 9000.0, 3700.0), (45.0, 8300.0, 3500.0),
                   (55.0, 7400.0, 3300.0), (65.0, 6300.0, 3000.0), (75.0, 4900.0, 2700.0)],
    },
    "sleep_efficiency_pct": {
        "source": (
            "Sleep efficiency declines with age in meta-analysed polysomnography norms "
            "(Ohayon et al., Sleep 2004)."
        ),
        "points": [(25.0, 92.0, 5.0), (35.0, 90.5, 5.3), (45.0, 88.5, 5.8),
                   (55.0, 86.0, 6.3), (65.0, 84.0, 6.8), (75.0, 82.0, 7.2)],
    },
    "bmi": {
        "source": "Adult BMI rises through midlife then plateaus (NHANES anthropometry).",
        "points": [(25.0, 26.5, 5.8), (35.0, 28.2, 6.2), (45.0, 29.2, 6.4),
                   (55.0, 29.6, 6.4), (65.0, 29.4, 6.1), (75.0, 28.4, 5.7)],
    },
}


def fit(points: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    """Return (q, k, s): intercept, age slope, and pooled residual SD."""
    ages = np.array([p[0] for p in points])
    means = np.array([p[1] for p in points])
    sds = np.array([p[2] for p in points])
    k, q = np.polyfit(ages, means, 1)
    # Residual SD combines within-stratum spread and lack of fit to the linear trend.
    lack_of_fit = float(np.sqrt(np.mean((means - (q + k * ages)) ** 2)))
    pooled_within = float(np.sqrt(np.mean(sds**2)))
    return float(q), float(k), float(np.hypot(pooled_within, lack_of_fit))


def main() -> None:
    biomarkers = {}
    for name, spec in NORMS.items():
        q, k, s = fit(spec["points"])  # type: ignore[arg-type]
        biomarkers[name] = {
            "q": round(q, 6),
            "k": round(k, 6),
            "s": round(s, 6),
            "source": spec["source"],
        }

    document = {
        "source": (
            "DERIVED by bioage.reference.regenerate_kdm from the published age-stratified "
            "normative tables embedded in that script. No primary NHANES q/k/s table "
            "exists for wearable-derived biomarkers, so these are reconstructed, not "
            "primary. See docs/METHODOLOGY.md."
        ),
        "derived": True,
        "min_biomarkers": 3,
        "s_ba": 11.0,
        "sigma_years": 6.5,
        "biomarkers": biomarkers,
    }

    out = Path(__file__).parent / "kdm_biomarkers.yaml"
    with out.open("w") as handle:
        yaml.safe_dump(document, handle, sort_keys=False, width=88)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Generate the YAML**

Run: `cd backend && uv run python -m bioage.reference.regenerate_kdm`
Expected: `wrote .../reference/kdm_biomarkers.yaml`, and the file contains five biomarkers each with `q`, `k`, `s`, `source`.

Sanity check the signs: `resting_hr_bpm.k` and `bmi.k` must be **positive** (rise with age); `hrv_rmssd_ms.k`, `mean_daily_steps.k`, `sleep_efficiency_pct.k` must be **negative** (fall with age). If any sign is wrong, the normative points are wrong.

- [ ] **Step 5: Extend the loader**

Append to `backend/src/bioage/reference/loader.py`:
```python
class KdmBiomarker(BaseModel):
    q: float
    k: float
    s: float
    source: str


class KdmConstants(Cited):
    min_biomarkers: int
    s_ba: float
    sigma_years: float
    biomarkers: dict[str, KdmBiomarker]


@lru_cache
def get_kdm() -> KdmConstants:
    return KdmConstants(**load_yaml("kdm_biomarkers"))
```

- [ ] **Step 6: Implement the estimator**

`backend/src/bioage/estimators/kdm.py`:
```python
"""Klemera-Doubal biological age.

For each biomarker j, the reference population satisfies x_j = q_j + k_j * age, with
residual standard deviation s_j. The Klemera-Doubal estimator inverts that system:

    BA_E = sum_j[(x_j - q_j) * k_j / s_j^2] / sum_j[k_j^2 / s_j^2]

and the corrected form pulls the estimate toward chronological age (CA) using the
characteristic variance s_BA^2:

    BA_EC = [sum_j((x_j - q_j) k_j / s_j^2) + CA / s_BA^2]
          / [sum_j(k_j^2 / s_j^2)          + 1  / s_BA^2]

The denominator squares k_j, not k_j/s_j^2. That distinction is load-bearing: only this
form satisfies BA_E == A when every biomarker sits exactly on its regression line.
"""

from __future__ import annotations

from dataclasses import dataclass

from bioage.estimators.models import BiomarkerVector, EstimatorResult, clamp_age
from bioage.reference.loader import get_kdm

COMPONENT = "kdm"


@dataclass(frozen=True)
class BiomarkerReference:
    """Reference regression of one biomarker on chronological age."""

    name: str
    q: float
    k: float
    s: float

    def __post_init__(self) -> None:
        if self.s <= 0:
            raise ValueError("s must be positive")
        if self.k == 0:
            raise ValueError("k must be non-zero")


def kdm_bio_age(
    observations: dict[str, float],
    references: dict[str, BiomarkerReference],
    chronological_age: float,
    s_ba: float | None,
) -> float:
    """Compute BA_E, or BA_EC when s_ba is supplied.

    Observations without a matching reference are ignored.
    """
    numerator = 0.0
    denominator = 0.0
    used = 0
    for name, value in observations.items():
        ref = references.get(name)
        if ref is None:
            continue
        weight = ref.k / ref.s**2
        numerator += (value - ref.q) * weight
        denominator += ref.k**2 / ref.s**2
        used += 1

    if used == 0:
        raise ValueError("no biomarkers overlap the supplied references")

    if s_ba is not None:
        if s_ba <= 0:
            raise ValueError("s_ba must be positive")
        numerator += chronological_age / s_ba**2
        denominator += 1.0 / s_ba**2

    return numerator / denominator


def _observations(vector: BiomarkerVector) -> dict[str, float]:
    candidates = {
        "resting_hr_bpm": vector.resting_hr_bpm,
        "hrv_rmssd_ms": vector.hrv_rmssd_ms,
        "mean_daily_steps": vector.mean_daily_steps,
        "sleep_efficiency_pct": vector.sleep_efficiency_pct,
        "bmi": vector.bmi,
    }
    return {name: value for name, value in candidates.items() if value is not None}


def kdm_age(vector: BiomarkerVector) -> EstimatorResult | None:
    """Return the KDM biological age, or None if too few biomarkers are available."""
    constants = get_kdm()
    references = {
        name: BiomarkerReference(name=name, q=marker.q, k=marker.k, s=marker.s)
        for name, marker in constants.biomarkers.items()
    }
    observations = {
        name: value for name, value in _observations(vector).items() if name in references
    }
    if len(observations) < constants.min_biomarkers:
        return None

    age = kdm_bio_age(
        observations, references, chronological_age=vector.chronological_age, s_ba=constants.s_ba
    )
    return EstimatorResult(
        component=COMPONENT,
        age_years=clamp_age(age),
        sigma_years=constants.sigma_years,
        inputs={**observations, "biomarker_count": float(len(observations))},
    )
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/estimators/test_kdm.py -v`
Expected: PASS — 15 passed (the identity test is parametrized 4 ways)

- [ ] **Step 8: Prove the incorrect formula fails the identity**

This step guards against someone "fixing" the code back to the source document's version.
Add to `backend/tests/estimators/test_kdm.py`:
```python
def test_the_source_documents_denominator_does_not_satisfy_the_identity():
    """Regression guard: sum((k/s^2)^2) is the wrong denominator.

    reference-research-from-claude.md prints it that way. Recomputing with it here shows
    it fails to recover A, which is why the implementation uses sum(k^2/s^2).
    """
    age = 50.0
    obs = _on_the_line(age)
    numerator = sum((obs[n] - r.q) * (r.k / r.s**2) for n, r in REFS.items())
    wrong_denominator = sum((r.k / r.s**2) ** 2 for r in REFS.values())
    assert numerator / wrong_denominator != pytest.approx(age, abs=1.0)
```

Run: `cd backend && uv run pytest tests/estimators/test_kdm.py -v`
Expected: PASS — 16 passed

- [ ] **Step 9: Commit**

```bash
git add backend/src/bioage/estimators/kdm.py backend/src/bioage/reference/kdm_biomarkers.yaml \
        backend/src/bioage/reference/regenerate_kdm.py backend/src/bioage/reference/loader.py \
        backend/tests/estimators/test_kdm.py
git commit -m "feat: Klemera-Doubal estimator with derived, auditable reference constants"
```

---

### Task 9: Composite combination

**Files:**
- Create: `backend/src/bioage/reference/composite.yaml`
- Modify: `backend/src/bioage/reference/loader.py` (add `CompositeConstants`, `get_composite()`)
- Create: `backend/src/bioage/estimators/composite.py`
- Create: `backend/tests/estimators/test_composite.py`

**Interfaces:**
- Consumes: `EstimatorResult`, `BiomarkerVector`, all four estimator entry points
- Produces:
  - `bioage.estimators.composite.CompositeResult` — frozen dataclass: `age_years: float`, `ci_low: float`, `ci_high: float`, `components: list[EstimatorResult]`, `is_low_confidence: bool`
  - `bioage.estimators.composite.combine(results: Sequence[EstimatorResult], low_confidence: bool = False) -> CompositeResult | None`
  - `bioage.estimators.composite.estimate_all(vector: BiomarkerVector, low_confidence: bool = False) -> CompositeResult | None`

- [ ] **Step 1: Write the failing test**

`backend/tests/estimators/test_composite.py`:
```python
import math

import pytest

from bioage.estimators.composite import combine, estimate_all
from bioage.estimators.models import BiomarkerVector, EstimatorResult
from bioage.types import Sex


def r(component: str, age: float, sigma: float) -> EstimatorResult:
    return EstimatorResult(component=component, age_years=age, sigma_years=sigma, inputs={})


def test_returns_none_with_fewer_than_two_components():
    assert combine([]) is None
    assert combine([r("kdm", 40.0, 5.0)]) is None


def test_equal_sigmas_produce_the_arithmetic_mean():
    result = combine([r("a", 40.0, 5.0), r("b", 50.0, 5.0)])
    assert result is not None
    assert result.age_years == pytest.approx(45.0)


def test_tighter_sigma_pulls_the_result_toward_it():
    result = combine([r("a", 40.0, 1.0), r("b", 60.0, 10.0)])
    assert result is not None
    assert result.age_years < 45.0


def test_inverse_variance_weighting_matches_hand_calculation():
    ages, sigmas = [40.0, 50.0], [4.0, 8.0]
    weights = [1 / s**2 for s in sigmas]
    expected = sum(a * w for a, w in zip(ages, weights)) / sum(weights)
    result = combine([r("a", ages[0], sigmas[0]), r("b", ages[1], sigmas[1])])
    assert result is not None
    assert result.age_years == pytest.approx(expected)


def test_confidence_interval_is_symmetric_and_uses_1_96_sigma():
    sigmas = [4.0, 8.0]
    combined_sigma = math.sqrt(1 / sum(1 / s**2 for s in sigmas))
    result = combine([r("a", 40.0, sigmas[0]), r("b", 50.0, sigmas[1])])
    assert result is not None
    half_width = (result.ci_high - result.ci_low) / 2
    assert half_width == pytest.approx(1.96 * combined_sigma)
    assert result.age_years == pytest.approx((result.ci_low + result.ci_high) / 2)


def test_adding_a_component_narrows_the_interval():
    two = combine([r("a", 40.0, 5.0), r("b", 50.0, 5.0)])
    three = combine([r("a", 40.0, 5.0), r("b", 50.0, 5.0), r("c", 45.0, 5.0)])
    assert two is not None and three is not None
    assert (three.ci_high - three.ci_low) < (two.ci_high - two.ci_low)


def test_low_confidence_widens_the_interval_and_sets_the_flag():
    normal = combine([r("a", 40.0, 5.0), r("b", 50.0, 5.0)], low_confidence=False)
    thin = combine([r("a", 40.0, 5.0), r("b", 50.0, 5.0)], low_confidence=True)
    assert normal is not None and thin is not None
    assert thin.is_low_confidence is True
    assert normal.is_low_confidence is False
    assert (thin.ci_high - thin.ci_low) > (normal.ci_high - normal.ci_low)
    assert thin.age_years == pytest.approx(normal.age_years)


def test_component_weights_from_reference_are_applied():
    """Components listed in composite.yaml get their sigma scaled by the configured factor."""
    from bioage.reference.loader import get_composite

    assert set(get_composite().sigma_multipliers) <= {
        "ntnu_fitness", "hrv_norm", "steps_mortality", "kdm"
    }


def test_estimate_all_drops_components_whose_inputs_are_missing():
    """No waist means NTNU cannot run; the composite must still work."""
    v = BiomarkerVector(
        chronological_age=40.0, sex=Sex.MALE, resting_hr_bpm=60.0, hrv_rmssd_ms=45.0,
        mean_daily_steps=9000.0, sleep_efficiency_pct=90.0, bmi=23.5, waist_cm=None,
    )
    result = estimate_all(v)
    assert result is not None
    assert "ntnu_fitness" not in {c.component for c in result.components}
    assert "hrv_norm" in {c.component for c in result.components}


def test_estimate_all_includes_all_four_when_everything_is_present():
    v = BiomarkerVector(
        chronological_age=40.0, sex=Sex.MALE, resting_hr_bpm=60.0, hrv_rmssd_ms=45.0,
        mean_daily_steps=9000.0, sleep_efficiency_pct=90.0, bmi=23.5, waist_cm=88.0,
        active_zone_minutes_per_day=25.0,
    )
    result = estimate_all(v)
    assert result is not None
    assert {c.component for c in result.components} == {
        "ntnu_fitness", "hrv_norm", "steps_mortality", "kdm"
    }


def test_estimate_all_returns_none_when_almost_nothing_is_available():
    v = BiomarkerVector(chronological_age=40.0, sex=Sex.MALE, resting_hr_bpm=60.0)
    assert estimate_all(v) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/estimators/test_composite.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bioage.estimators.composite'`

- [ ] **Step 3: Write the composite YAML**

`backend/src/bioage/reference/composite.yaml`:
```yaml
source: >-
  Weighting follows the reliability guidance in reference-research-from-claude.md: resting
  heart rate, HRV trend and step volume carry the most signal; wrist-PPG HRV is noisier
  than ECG and is downweighted accordingly. SpO2 and skin temperature are deliberately
  excluded as age components and surface only as trend context.
derived: true

z_score: 1.96

# Multiplies each component's own sigma before inverse-variance weighting. Values above
# 1.0 downweight a component.
sigma_multipliers:
  ntnu_fitness: 1.0
  kdm: 1.0
  steps_mortality: 1.1
  hrv_norm: 1.3

# Applied to the combined sigma when the week's data coverage is thin.
low_confidence_sigma_multiplier: 1.6

min_components: 2
```

- [ ] **Step 4: Extend the loader**

Append to `backend/src/bioage/reference/loader.py`:
```python
class CompositeConstants(Cited):
    z_score: float
    sigma_multipliers: dict[str, float]
    low_confidence_sigma_multiplier: float
    min_components: int


@lru_cache
def get_composite() -> CompositeConstants:
    return CompositeConstants(**load_yaml("composite"))
```

- [ ] **Step 5: Implement the composite**

`backend/src/bioage/estimators/composite.py`:
```python
"""Combine independent component estimates into one number with a confidence band.

Components are combined by inverse-variance weighting, which is the maximum-likelihood
combination of independent estimates of the same quantity:

    age   = sum(age_i / sigma_i^2) / sum(1 / sigma_i^2)
    sigma = sqrt(1 / sum(1 / sigma_i^2))

A composite is refused below `min_components`, because a single estimator dressed up as
a consensus would misrepresent its own uncertainty.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from bioage.estimators.hrv_norm import hrv_age
from bioage.estimators.kdm import kdm_age
from bioage.estimators.models import BiomarkerVector, EstimatorResult
from bioage.estimators.ntnu import fitness_age
from bioage.estimators.steps_mortality import steps_age
from bioage.reference.loader import get_composite

ESTIMATORS = (fitness_age, hrv_age, steps_age, kdm_age)


@dataclass(frozen=True)
class CompositeResult:
    age_years: float
    ci_low: float
    ci_high: float
    components: list[EstimatorResult]
    is_low_confidence: bool


def combine(
    results: Sequence[EstimatorResult],
    low_confidence: bool = False,
) -> CompositeResult | None:
    """Inverse-variance combination of component estimates."""
    constants = get_composite()
    if len(results) < constants.min_components:
        return None

    weighted_sum = 0.0
    weight_total = 0.0
    for result in results:
        multiplier = constants.sigma_multipliers.get(result.component, 1.0)
        sigma = result.sigma_years * multiplier
        weight = 1.0 / sigma**2
        weighted_sum += result.age_years * weight
        weight_total += weight

    age = weighted_sum / weight_total
    sigma = math.sqrt(1.0 / weight_total)
    if low_confidence:
        sigma *= constants.low_confidence_sigma_multiplier

    half_width = constants.z_score * sigma
    return CompositeResult(
        age_years=age,
        ci_low=age - half_width,
        ci_high=age + half_width,
        components=list(results),
        is_low_confidence=low_confidence,
    )


def estimate_all(
    vector: BiomarkerVector,
    low_confidence: bool = False,
) -> CompositeResult | None:
    """Run every estimator whose inputs are available, then combine."""
    results = [result for estimator in ESTIMATORS if (result := estimator(vector)) is not None]
    return combine(results, low_confidence=low_confidence)
```

- [ ] **Step 6: Run the whole estimator suite**

Run: `cd backend && uv run pytest tests/estimators -v`
Expected: PASS — all estimator tests green

- [ ] **Step 7: Verify purity — no I/O leaked into the science layer**

Run:
```bash
cd backend && ! grep -rnE "from bioage\.(db|api|ingest)|import (requests|httpx|sqlalchemy)" src/bioage/estimators/ && echo "estimators are pure"
```
Expected: `estimators are pure`

- [ ] **Step 8: Type-check the science layer**

Run: `cd backend && uv run mypy src/bioage/estimators src/bioage/reference`
Expected: `Success: no issues found`

- [ ] **Step 9: Commit**

```bash
git add backend/src/bioage/estimators/composite.py backend/src/bioage/reference/composite.yaml \
        backend/src/bioage/reference/loader.py backend/tests/estimators/test_composite.py
git commit -m "feat: inverse-variance composite with confidence band and graceful degradation"
```

---

## Phase C — Persistence

### Task 10: ORM models and the initial migration

**Files:**
- Create: `backend/src/bioage/db/__init__.py`
- Create: `backend/src/bioage/db/base.py`
- Create: `backend/src/bioage/db/models.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/0001_initial.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_db_models.py`

**Interfaces:**
- Consumes: `bioage.config.get_settings`, `bioage.types.Sex`
- Produces:
  - `bioage.db.base.Base`, `bioage.db.base.session_factory(url: str)`, `bioage.db.base.get_engine(url: str)`
  - `bioage.db.models.RawDataPoint(id, data_type, point_date, payload, ingested_at)` — unique `(data_type, point_date)`
  - `bioage.db.models.DailyMetric(date PK, resting_hr_bpm, hrv_rmssd_ms, hrv_average_ms, steps, active_zone_minutes, sleep_total_min, sleep_efficiency_pct, waso_min, deep_pct, rem_pct, sleep_midpoint_local_min, respiratory_rate_brpm, spo2_pct, skin_temp_delta_c, weight_kg, height_m)` — every field nullable except `date`
  - `bioage.db.models.Profile(id PK=1, sex, birthdate)` — singleton
  - `bioage.db.models.Measurement(id, kind, value, measured_on)` — `kind` in `{"height_m","weight_kg","waist_cm"}`
  - `bioage.db.models.BioAgeScore(week_start PK, chronological_age, composite_age, ci_low, ci_high, components, coverage, is_low_confidence, computed_at)`
  - `bioage.db.models.OAuthCredential(id PK=1, refresh_token, access_token, token_expiry, scopes, connected_at)`
  - `bioage.db.models.SyncState(data_type PK, synced_through, last_run_at, last_error)`

- [ ] **Step 1: Write the failing test**

`backend/tests/conftest.py`:
```python
"""Shared fixtures.

Integration tests need a real Postgres because the schema uses JSONB. Point
TEST_DATABASE_URL at a scratch database; `docker compose up -d db` provides one.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from bioage.db.base import Base

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://bioage:bioage@localhost:5432/bioage_test"
)


@pytest.fixture(scope="session")
def engine():
    admin_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    db_name = TEST_DATABASE_URL.rsplit("/", 1)[1]
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin.dispose()

    eng = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine) -> Iterator[Session]:
    """A session rolled back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
```

`backend/tests/test_db_models.py`:
```python
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from bioage.db.models import (
    BioAgeScore,
    DailyMetric,
    Measurement,
    Profile,
    RawDataPoint,
    SyncState,
)
from bioage.types import Sex


def test_raw_data_point_round_trips_jsonb(db):
    db.add(RawDataPoint(
        data_type="daily-resting-heart-rate",
        point_date=date(2026, 6, 1),
        payload={"dailyRestingHeartRate": {"beatsPerMinute": "58"}},
    ))
    db.flush()
    stored = db.query(RawDataPoint).one()
    assert stored.payload["dailyRestingHeartRate"]["beatsPerMinute"] == "58"


def test_raw_data_point_rejects_duplicate_type_and_date(db):
    for _ in range(2):
        db.add(RawDataPoint(
            data_type="steps", point_date=date(2026, 6, 1), payload={},
        ))
    with pytest.raises(IntegrityError):
        db.flush()


def test_daily_metric_allows_every_measurement_to_be_null(db):
    db.add(DailyMetric(date=date(2026, 6, 1)))
    db.flush()
    stored = db.query(DailyMetric).one()
    assert stored.resting_hr_bpm is None
    assert stored.steps is None


def test_profile_stores_sex_as_enum_value(db):
    db.add(Profile(id=1, sex=Sex.MALE, birthdate=date(1990, 3, 14)))
    db.flush()
    assert db.query(Profile).one().sex is Sex.MALE


def test_measurements_are_dated_and_multiple_per_kind(db):
    db.add_all([
        Measurement(kind="waist_cm", value=88.0, measured_on=date(2026, 5, 1)),
        Measurement(kind="waist_cm", value=86.0, measured_on=date(2026, 7, 1)),
    ])
    db.flush()
    assert db.query(Measurement).count() == 2


def test_bioage_score_stores_components_as_jsonb(db):
    db.add(BioAgeScore(
        week_start=date(2026, 6, 1),
        chronological_age=36.2,
        composite_age=33.8,
        ci_low=28.1,
        ci_high=39.5,
        components=[{"component": "kdm", "age_years": 34.0}],
        coverage={"rhr_days": 27},
        is_low_confidence=False,
        computed_at=datetime.now(timezone.utc),
    ))
    db.flush()
    assert db.query(BioAgeScore).one().components[0]["component"] == "kdm"


def test_sync_state_is_keyed_by_data_type(db):
    db.add(SyncState(data_type="steps", synced_through=date(2026, 7, 1)))
    db.flush()
    assert db.query(SyncState).one().data_type == "steps"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose up -d db && cd backend && uv run pytest tests/test_db_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bioage.db'`

- [ ] **Step 3: Implement the base**

`backend/src/bioage/db/__init__.py`: empty file.

`backend/src/bioage/db/base.py`:
```python
"""SQLAlchemy engine, session factory, and declarative base."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True)


@lru_cache
def session_factory(url: str) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(url), expire_on_commit=False)
```

- [ ] **Step 4: Implement the models**

`backend/src/bioage/db/models.py`:
```python
"""ORM models.

Raw payloads are stored before parsing so that a parser fix is a re-parse rather than a
re-fetch of data that may have aged out of the API's queryable window.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from bioage.db.base import Base
from bioage.types import Sex

MEASUREMENT_KINDS = ("height_m", "weight_kg", "waist_cm")


class RawDataPoint(Base):
    __tablename__ = "raw_data_points"
    __table_args__ = (UniqueConstraint("data_type", "point_date", name="uq_raw_type_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    data_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    point_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DailyMetric(Base):
    """One normalized row per calendar day. Every measurement is optional."""

    __tablename__ = "daily_metrics"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    resting_hr_bpm: Mapped[float | None] = mapped_column(Float)
    hrv_rmssd_ms: Mapped[float | None] = mapped_column(Float)
    hrv_average_ms: Mapped[float | None] = mapped_column(Float)
    steps: Mapped[int | None] = mapped_column(Integer)
    active_zone_minutes: Mapped[int | None] = mapped_column(Integer)
    sleep_total_min: Mapped[float | None] = mapped_column(Float)
    sleep_efficiency_pct: Mapped[float | None] = mapped_column(Float)
    waso_min: Mapped[float | None] = mapped_column(Float)
    deep_pct: Mapped[float | None] = mapped_column(Float)
    rem_pct: Mapped[float | None] = mapped_column(Float)
    sleep_midpoint_local_min: Mapped[float | None] = mapped_column(Float)
    respiratory_rate_brpm: Mapped[float | None] = mapped_column(Float)
    spo2_pct: Mapped[float | None] = mapped_column(Float)
    skin_temp_delta_c: Mapped[float | None] = mapped_column(Float)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    height_m: Mapped[float | None] = mapped_column(Float)


class Profile(Base):
    """Singleton row: this is a single-user application."""

    __tablename__ = "profile"
    __table_args__ = (CheckConstraint("id = 1", name="ck_profile_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    sex: Mapped[Sex] = mapped_column(Enum(Sex, name="sex", values_callable=lambda e: [m.value for m in e]), nullable=False)
    birthdate: Mapped[date] = mapped_column(Date, nullable=False)


class Measurement(Base):
    """A dated body measurement.

    Dating matters: re-measuring your waist must not retroactively rewrite earlier
    weekly scores.
    """

    __tablename__ = "measurements"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('height_m', 'weight_kg', 'waist_cm')", name="ck_measurement_kind"
        ),
        UniqueConstraint("kind", "measured_on", name="uq_measurement_kind_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    measured_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)


class BioAgeScore(Base):
    __tablename__ = "bioage_scores"

    week_start: Mapped[date] = mapped_column(Date, primary_key=True)
    chronological_age: Mapped[float] = mapped_column(Float, nullable=False)
    composite_age: Mapped[float] = mapped_column(Float, nullable=False)
    ci_low: Mapped[float] = mapped_column(Float, nullable=False)
    ci_high: Mapped[float] = mapped_column(Float, nullable=False)
    components: Mapped[list] = mapped_column(JSONB, nullable=False)
    coverage: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_low_confidence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OAuthCredential(Base):
    __tablename__ = "oauth_credentials"
    __table_args__ = (CheckConstraint("id = 1", name="ck_oauth_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    access_token: Mapped[str | None] = mapped_column(Text)
    token_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SyncState(Base):
    """Per-data-type watermark, so incremental syncs fetch only what is new."""

    __tablename__ = "sync_state"

    data_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    synced_through: Mapped[date | None] = mapped_column(Date)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_db_models.py -v`
Expected: PASS — 7 passed

- [ ] **Step 6: Wire up Alembic**

Run: `cd backend && uv run alembic init -t generic alembic`

Then edit `backend/alembic/env.py`, replacing its config section with:
```python
import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from bioage.db.base import Base
from bioage.db import models  # noqa: F401  (import registers the tables)

config = context.config
config.set_main_option(
    "sqlalchemy.url",
    os.environ.get("DATABASE_URL", "postgresql+psycopg://bioage:bioage@localhost:5432/bioage"),
)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 7: Autogenerate and apply the initial migration**

Run:
```bash
cd backend
DATABASE_URL=postgresql+psycopg://bioage:bioage@localhost:5432/bioage \
  uv run alembic revision --autogenerate -m "initial schema"
DATABASE_URL=postgresql+psycopg://bioage:bioage@localhost:5432/bioage \
  uv run alembic upgrade head
```
Expected: a file appears in `alembic/versions/`, and `upgrade head` completes without error.

- [ ] **Step 8: Verify the migration reverses cleanly**

Run:
```bash
cd backend
export DATABASE_URL=postgresql+psycopg://bioage:bioage@localhost:5432/bioage
uv run alembic downgrade base && uv run alembic upgrade head
```
Expected: both complete without error. A migration that cannot be reversed is a migration that cannot be tested.

- [ ] **Step 9: Commit**

```bash
git add backend/src/bioage/db backend/alembic backend/alembic.ini \
        backend/tests/conftest.py backend/tests/test_db_models.py
git commit -m "feat: ORM models and initial Alembic migration"
```

---

## Phase D — Normalization

### Task 11: Proto-JSON coercion helpers

**Files:**
- Create: `backend/src/bioage/biomarkers/__init__.py`
- Create: `backend/src/bioage/biomarkers/parsers/__init__.py`
- Create: `backend/src/bioage/biomarkers/parsers/common.py`
- Create: `backend/tests/biomarkers/__init__.py`
- Create: `backend/tests/biomarkers/test_parser_common.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `parse_proto_date(value: dict) -> date` — `{"year":2026,"month":6,"day":1}` → `date`
  - `parse_duration_seconds(value: str) -> float` — `"28800s"` → `28800.0`
  - `parse_int64(value: str | int | None) -> int | None` — proto int64 arrives as a string
  - `parse_double(value: float | str | None) -> float | None`
  - `parse_timestamp(value: str) -> datetime` — RFC3339, always timezone-aware

- [ ] **Step 1: Write the failing test**

`backend/tests/biomarkers/test_parser_common.py`:
```python
from datetime import date, datetime, timezone

import pytest

from bioage.biomarkers.parsers.common import (
    parse_double,
    parse_duration_seconds,
    parse_int64,
    parse_proto_date,
    parse_timestamp,
)


def test_proto_date_uses_year_month_day_fields_not_an_iso_string():
    assert parse_proto_date({"year": 2026, "month": 6, "day": 1}) == date(2026, 6, 1)


def test_proto_date_rejects_missing_fields():
    with pytest.raises(ValueError, match="incomplete proto Date"):
        parse_proto_date({"year": 2026, "month": 6})


def test_duration_parses_the_trailing_s_suffix():
    assert parse_duration_seconds("28800s") == 28800.0


def test_duration_parses_fractional_seconds():
    assert parse_duration_seconds("1.500s") == pytest.approx(1.5)


def test_duration_rejects_a_missing_suffix():
    with pytest.raises(ValueError, match="duration must end with 's'"):
        parse_duration_seconds("28800")


def test_int64_accepts_the_string_encoding_the_api_actually_sends():
    assert parse_int64("12345") == 12345


def test_int64_also_accepts_a_real_integer():
    assert parse_int64(9000) == 9000


def test_int64_passes_none_through():
    assert parse_int64(None) is None


def test_double_accepts_number_and_string():
    assert parse_double(58.5) == pytest.approx(58.5)
    assert parse_double("58.5") == pytest.approx(58.5)
    assert parse_double(None) is None


def test_timestamp_is_always_timezone_aware():
    parsed = parse_timestamp("2026-06-01T23:14:00Z")
    assert parsed == datetime(2026, 6, 1, 23, 14, tzinfo=timezone.utc)
    assert parsed.tzinfo is not None


def test_timestamp_accepts_explicit_offsets():
    parsed = parse_timestamp("2026-06-01T23:14:00+02:00")
    assert parsed.utcoffset().total_seconds() == 7200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/biomarkers/test_parser_common.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bioage.biomarkers'`

- [ ] **Step 3: Implement the helpers**

`backend/src/bioage/biomarkers/__init__.py`, `backend/src/bioage/biomarkers/parsers/__init__.py`: empty files for now.

`backend/src/bioage/biomarkers/parsers/common.py`:
```python
"""Coercion helpers for Google Health API proto-JSON encoding.

Three encoding quirks bite repeatedly:
  * `google.type.Date` is an object {year, month, day}, not an ISO-8601 string.
  * `google.protobuf.Duration` is a string with a trailing 's', e.g. "28800s".
  * `int64` fields are JSON *strings*, because JSON numbers cannot hold 64-bit integers
    safely. Reading them as numbers works until it silently does not.
"""

from __future__ import annotations

from datetime import date, datetime


def parse_proto_date(value: dict) -> date:
    try:
        return date(int(value["year"]), int(value["month"]), int(value["day"]))
    except KeyError as exc:
        raise ValueError(f"incomplete proto Date: {value!r}") from exc


def parse_duration_seconds(value: str) -> float:
    if not isinstance(value, str) or not value.endswith("s"):
        raise ValueError(f"duration must end with 's': {value!r}")
    return float(value[:-1])


def parse_int64(value: str | int | None) -> int | None:
    if value is None:
        return None
    return int(value)


def parse_double(value: float | str | None) -> float | None:
    if value is None:
        return None
    return float(value)


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must carry a timezone: {value!r}")
    return parsed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/biomarkers/test_parser_common.py -v`
Expected: PASS — 11 passed

- [ ] **Step 5: Commit**

```bash
git add backend/src/bioage/biomarkers backend/tests/biomarkers
git commit -m "feat: proto-JSON coercion helpers for Date, Duration and int64 encodings"
```

---

### Task 12: Daily, interval and sample parsers

**Files:**
- Create: `backend/src/bioage/biomarkers/parsers/daily.py`
- Create: `backend/src/bioage/biomarkers/parsers/interval.py`
- Create: `backend/src/bioage/biomarkers/parsers/sample.py`
- Create: `backend/tests/fixtures/googlehealth/daily_resting_heart_rate.json`
- Create: `backend/tests/fixtures/googlehealth/daily_heart_rate_variability.json`
- Create: `backend/tests/fixtures/googlehealth/steps.json`
- Create: `backend/tests/fixtures/googlehealth/daily_oxygen_saturation.json`
- Create: `backend/tests/fixtures/googlehealth/empty.json`
- Create: `backend/tests/biomarkers/test_parsers_daily.py`

**Interfaces:**
- Consumes: `parsers.common` helpers
- Produces: `ParsedPoint` frozen dataclass (`day: date`, `values: dict[str, float]`) and one parser per data type, each with signature `(payload: dict) -> ParsedPoint | None`:
  - `parse_daily_resting_heart_rate` → `{"resting_hr_bpm": float}`
  - `parse_daily_heart_rate_variability` → `{"hrv_rmssd_ms": float, "hrv_average_ms": float}`
  - `parse_daily_respiratory_rate` → `{"respiratory_rate_brpm": float}`
  - `parse_daily_oxygen_saturation` → `{"spo2_pct": float}`
  - `parse_daily_sleep_temperature_derivations` → `{"skin_temp_delta_c": float}`
  - `parse_steps` → `{"steps": float}` (interval, attributed to the local start date)
  - `parse_active_zone_minutes` → `{"active_zone_minutes": float}`
  - `parse_weight` → `{"weight_kg": float}`; `parse_height` → `{"height_m": float}`

- [ ] **Step 1: Write the fixtures**

`backend/tests/fixtures/googlehealth/daily_resting_heart_rate.json`:
```json
{
  "dataPoints": [
    {
      "name": "users/me/dataTypes/daily-resting-heart-rate/dataPoints/p1",
      "dailyRestingHeartRate": {
        "date": {"year": 2026, "month": 6, "day": 1},
        "beatsPerMinute": "58"
      }
    },
    {
      "name": "users/me/dataTypes/daily-resting-heart-rate/dataPoints/p2",
      "dailyRestingHeartRate": {
        "date": {"year": 2026, "month": 6, "day": 2},
        "beatsPerMinute": "61"
      }
    }
  ]
}
```

`backend/tests/fixtures/googlehealth/daily_heart_rate_variability.json`:
```json
{
  "dataPoints": [
    {
      "name": "users/me/dataTypes/daily-heart-rate-variability/dataPoints/h1",
      "dailyHeartRateVariability": {
        "date": {"year": 2026, "month": 6, "day": 1},
        "averageHeartRateVariabilityMilliseconds": 41.2,
        "nonRemHeartRateBeatsPerMinute": "54",
        "entropy": 1.83,
        "deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds": 46.7
      }
    },
    {
      "name": "users/me/dataTypes/daily-heart-rate-variability/dataPoints/h2",
      "dailyHeartRateVariability": {
        "date": {"year": 2026, "month": 6, "day": 2},
        "averageHeartRateVariabilityMilliseconds": 38.9
      }
    }
  ]
}
```

`backend/tests/fixtures/googlehealth/steps.json`:
```json
{
  "dataPoints": [
    {
      "name": "users/me/dataTypes/steps/dataPoints/s1",
      "steps": {
        "interval": {
          "startTime": "2026-06-01T00:00:00Z",
          "endTime": "2026-06-02T00:00:00Z"
        },
        "count": "10432"
      }
    }
  ],
  "nextPageToken": ""
}
```

`backend/tests/fixtures/googlehealth/daily_oxygen_saturation.json`:
```json
{
  "dataPoints": [
    {
      "name": "users/me/dataTypes/daily-oxygen-saturation/dataPoints/o1",
      "dailyOxygenSaturation": {
        "date": {"year": 2026, "month": 6, "day": 1},
        "averagePercentage": 96.4,
        "lowerBoundPercentage": 93.1,
        "upperBoundPercentage": 99.0,
        "standardDeviationPercentage": 1.2
      }
    }
  ]
}
```

`backend/tests/fixtures/googlehealth/empty.json`:
```json
{"dataPoints": []}
```

- [ ] **Step 2: Write the failing test**

`backend/tests/biomarkers/test_parsers_daily.py`:
```python
import json
from datetime import date
from pathlib import Path

import pytest

from bioage.biomarkers.parsers.daily import (
    parse_daily_heart_rate_variability,
    parse_daily_oxygen_saturation,
    parse_daily_resting_heart_rate,
    parse_daily_sleep_temperature_derivations,
)
from bioage.biomarkers.parsers.interval import parse_active_zone_minutes, parse_steps
from bioage.biomarkers.parsers.sample import parse_height, parse_weight

FIXTURES = Path(__file__).parent.parent / "fixtures" / "googlehealth"


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def test_resting_heart_rate_coerces_the_string_int64():
    point = load("daily_resting_heart_rate")["dataPoints"][0]
    parsed = parse_daily_resting_heart_rate(point)
    assert parsed is not None
    assert parsed.day == date(2026, 6, 1)
    assert parsed.values["resting_hr_bpm"] == pytest.approx(58.0)


def test_hrv_prefers_deep_sleep_rmssd_over_the_average():
    point = load("daily_heart_rate_variability")["dataPoints"][0]
    parsed = parse_daily_heart_rate_variability(point)
    assert parsed is not None
    assert parsed.values["hrv_rmssd_ms"] == pytest.approx(46.7)
    assert parsed.values["hrv_average_ms"] == pytest.approx(41.2)


def test_hrv_falls_back_to_the_average_when_rmssd_is_absent():
    point = load("daily_heart_rate_variability")["dataPoints"][1]
    parsed = parse_daily_heart_rate_variability(point)
    assert parsed is not None
    assert parsed.values["hrv_rmssd_ms"] == pytest.approx(38.9)


def test_oxygen_saturation_uses_the_average_percentage():
    point = load("daily_oxygen_saturation")["dataPoints"][0]
    parsed = parse_daily_oxygen_saturation(point)
    assert parsed is not None
    assert parsed.values["spo2_pct"] == pytest.approx(96.4)


def test_steps_coerces_the_string_count_and_dates_by_interval_start():
    point = load("steps")["dataPoints"][0]
    parsed = parse_steps(point)
    assert parsed is not None
    assert parsed.day == date(2026, 6, 1)
    assert parsed.values["steps"] == pytest.approx(10432.0)


def test_sleep_temperature_uses_the_relative_nightly_deviation():
    point = {
        "dailySleepTemperatureDerivations": {
            "date": {"year": 2026, "month": 6, "day": 1},
            "nightlyTemperatureCelsius": 33.8,
            "baselineTemperatureCelsius": 33.5,
            "relativeNightlyStddev30dCelsius": 0.3,
        }
    }
    parsed = parse_daily_sleep_temperature_derivations(point)
    assert parsed is not None
    assert parsed.values["skin_temp_delta_c"] == pytest.approx(0.3)


def test_active_zone_minutes_coerces_the_string_count():
    point = {
        "activeZoneMinutes": {
            "interval": {
                "startTime": "2026-06-01T00:00:00Z",
                "endTime": "2026-06-02T00:00:00Z",
            },
            "heartRateZone": "FAT_BURN",
            "activeZoneMinutes": "27",
        }
    }
    parsed = parse_active_zone_minutes(point)
    assert parsed is not None
    assert parsed.values["active_zone_minutes"] == pytest.approx(27.0)


def test_weight_and_height_use_sample_time():
    weight = parse_weight({
        "weight": {"sampleTime": {"time": "2026-06-01T07:30:00Z"}, "kilograms": 74.3}
    })
    assert weight is not None
    assert weight.day == date(2026, 6, 1)
    assert weight.values["weight_kg"] == pytest.approx(74.3)

    height = parse_height({
        "height": {"sampleTime": {"time": "2026-06-01T07:30:00Z"}, "meters": 1.78}
    })
    assert height is not None
    assert height.values["height_m"] == pytest.approx(1.78)


def test_weight_accepts_the_alternative_grams_encoding():
    """The dataPoints overview documents weightGrams while the RPC reference documents
    kilograms. Accept either rather than silently dropping the field."""
    parsed = parse_weight({
        "weight": {"sampleTime": {"time": "2026-06-01T07:30:00Z"}, "weightGrams": 74300}
    })
    assert parsed is not None
    assert parsed.values["weight_kg"] == pytest.approx(74.3)


@pytest.mark.parametrize(
    "parser",
    [
        parse_daily_resting_heart_rate,
        parse_daily_heart_rate_variability,
        parse_daily_oxygen_saturation,
        parse_steps,
        parse_weight,
    ],
)
def test_every_parser_returns_none_for_an_unrelated_payload(parser):
    assert parser({"somethingElse": {}}) is None


def test_parser_returns_none_when_the_value_field_is_missing():
    point = {"dailyRestingHeartRate": {"date": {"year": 2026, "month": 6, "day": 1}}}
    assert parse_daily_resting_heart_rate(point) is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/biomarkers/test_parsers_daily.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bioage.biomarkers.parsers.daily'`

- [ ] **Step 4: Implement the parsers**

`backend/src/bioage/biomarkers/parsers/daily.py`:
```python
"""Parsers for daily-aggregated data types.

Every parser is total: it returns None rather than raising when the payload is not the
type it handles or when the value field is absent. Missing days are the normal case for
a wearable, not an error condition.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from bioage.biomarkers.parsers.common import parse_double, parse_int64, parse_proto_date


@dataclass(frozen=True)
class ParsedPoint:
    day: date
    values: dict[str, float]


def _daily_body(payload: dict, key: str) -> dict | None:
    body = payload.get(key)
    if not isinstance(body, dict) or "date" not in body:
        return None
    return body


def parse_daily_resting_heart_rate(payload: dict) -> ParsedPoint | None:
    body = _daily_body(payload, "dailyRestingHeartRate")
    if body is None:
        return None
    bpm = parse_int64(body.get("beatsPerMinute"))
    if bpm is None:
        return None
    return ParsedPoint(parse_proto_date(body["date"]), {"resting_hr_bpm": float(bpm)})


def parse_daily_heart_rate_variability(payload: dict) -> ParsedPoint | None:
    """Prefer deep-sleep RMSSD; the HRV-norm estimator is calibrated against RMSSD."""
    body = _daily_body(payload, "dailyHeartRateVariability")
    if body is None:
        return None
    rmssd = parse_double(
        body.get("deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds")
    )
    average = parse_double(body.get("averageHeartRateVariabilityMilliseconds"))
    effective = rmssd if rmssd is not None else average
    if effective is None:
        return None
    values = {"hrv_rmssd_ms": effective}
    if average is not None:
        values["hrv_average_ms"] = average
    return ParsedPoint(parse_proto_date(body["date"]), values)


def parse_daily_respiratory_rate(payload: dict) -> ParsedPoint | None:
    body = _daily_body(payload, "dailyRespiratoryRate")
    if body is None:
        return None
    rate = parse_double(body.get("breathsPerMinute"))
    if rate is None:
        return None
    return ParsedPoint(parse_proto_date(body["date"]), {"respiratory_rate_brpm": rate})


def parse_daily_oxygen_saturation(payload: dict) -> ParsedPoint | None:
    body = _daily_body(payload, "dailyOxygenSaturation")
    if body is None:
        return None
    average = parse_double(body.get("averagePercentage"))
    if average is None:
        return None
    return ParsedPoint(parse_proto_date(body["date"]), {"spo2_pct": average})


def parse_daily_sleep_temperature_derivations(payload: dict) -> ParsedPoint | None:
    """Skin temperature is used only as a multi-week trend, never as a nightly value."""
    body = _daily_body(payload, "dailySleepTemperatureDerivations")
    if body is None:
        return None
    delta = parse_double(body.get("relativeNightlyStddev30dCelsius"))
    if delta is None:
        nightly = parse_double(body.get("nightlyTemperatureCelsius"))
        baseline = parse_double(body.get("baselineTemperatureCelsius"))
        if nightly is None or baseline is None:
            return None
        delta = nightly - baseline
    return ParsedPoint(parse_proto_date(body["date"]), {"skin_temp_delta_c": delta})
```

`backend/src/bioage/biomarkers/parsers/interval.py`:
```python
"""Parsers for interval data types, attributed to the interval's start date."""

from __future__ import annotations

from bioage.biomarkers.parsers.common import parse_int64, parse_timestamp
from bioage.biomarkers.parsers.daily import ParsedPoint


def _interval_start_day(body: dict):
    interval = body.get("interval")
    if not isinstance(interval, dict) or "startTime" not in interval:
        return None
    return parse_timestamp(interval["startTime"]).date()


def parse_steps(payload: dict) -> ParsedPoint | None:
    body = payload.get("steps")
    if not isinstance(body, dict):
        return None
    day = _interval_start_day(body)
    count = parse_int64(body.get("count"))
    if day is None or count is None:
        return None
    return ParsedPoint(day, {"steps": float(count)})


def parse_active_zone_minutes(payload: dict) -> ParsedPoint | None:
    body = payload.get("activeZoneMinutes")
    if not isinstance(body, dict):
        return None
    day = _interval_start_day(body)
    minutes = parse_int64(body.get("activeZoneMinutes"))
    if day is None or minutes is None:
        return None
    return ParsedPoint(day, {"active_zone_minutes": float(minutes)})
```

`backend/src/bioage/biomarkers/parsers/sample.py`:
```python
"""Parsers for instantaneous sample data types."""

from __future__ import annotations

from bioage.biomarkers.parsers.common import parse_double, parse_timestamp
from bioage.biomarkers.parsers.daily import ParsedPoint


def _sample_day(body: dict):
    sample_time = body.get("sampleTime")
    if not isinstance(sample_time, dict) or "time" not in sample_time:
        return None
    return parse_timestamp(sample_time["time"]).date()


def parse_weight(payload: dict) -> ParsedPoint | None:
    body = payload.get("weight")
    if not isinstance(body, dict):
        return None
    day = _sample_day(body)
    if day is None:
        return None
    kilograms = parse_double(body.get("kilograms"))
    if kilograms is None:
        grams = parse_double(body.get("weightGrams"))
        if grams is None:
            return None
        kilograms = grams / 1000.0
    return ParsedPoint(day, {"weight_kg": kilograms})


def parse_height(payload: dict) -> ParsedPoint | None:
    body = payload.get("height")
    if not isinstance(body, dict):
        return None
    day = _sample_day(body)
    meters = parse_double(body.get("meters"))
    if day is None or meters is None:
        return None
    return ParsedPoint(day, {"height_m": meters})
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/biomarkers/test_parsers_daily.py -v`
Expected: PASS — 15 passed

- [ ] **Step 6: Commit**

```bash
git add backend/src/bioage/biomarkers/parsers backend/tests/fixtures backend/tests/biomarkers
git commit -m "feat: parsers for daily, interval and sample Google Health data types"
```

---

### Task 13: Sleep parser with derived efficiency and WASO

**Files:**
- Create: `backend/src/bioage/biomarkers/parsers/sleep.py`
- Create: `backend/tests/fixtures/googlehealth/sleep.json`
- Create: `backend/tests/fixtures/googlehealth/sleep_no_stages.json`
- Create: `backend/tests/biomarkers/test_parser_sleep.py`

**Interfaces:**
- Consumes: `parsers.common`, `ParsedPoint`
- Produces: `parse_sleep(payload: dict) -> ParsedPoint | None` yielding
  `{"sleep_total_min", "sleep_efficiency_pct", "waso_min", "deep_pct", "rem_pct", "sleep_midpoint_local_min"}`.
  Stage-dependent keys are omitted when `sleepMetadata.stagesState != "STAGES_AVAILABLE"`.
  The point is dated to the **wake date** (session end), which is how sleep is conventionally attributed to a night.

> The live `Sleep` message carries no efficiency or WASO field. Both are derived:
> `time_in_bed = end − start`; `asleep = LIGHT + DEEP + REM`; `efficiency = asleep/time_in_bed×100`;
> `WASO = AWAKE stages strictly between the first and last non-awake stage` (leading and
> trailing wakefulness is not WASO); `deep_pct`/`rem_pct` are fractions of `asleep`.

- [ ] **Step 1: Write the fixtures**

`backend/tests/fixtures/googlehealth/sleep.json`:
```json
{
  "dataPoints": [
    {
      "name": "users/me/dataTypes/sleep/dataPoints/n1",
      "sleep": {
        "session": {
          "startTime": "2026-05-31T23:00:00Z",
          "endTime": "2026-06-01T07:00:00Z"
        },
        "sleepMetadata": {"stagesState": "STAGES_AVAILABLE"},
        "sleepSummary": {
          "totalDuration": "28800s",
          "stageSummary": [
            {"stage": "AWAKE", "duration": "2400s"},
            {"stage": "LIGHT", "duration": "14400s"},
            {"stage": "DEEP", "duration": "5400s"},
            {"stage": "REM", "duration": "6600s"}
          ]
        },
        "sleepStages": [
          {"startTime": "2026-05-31T23:00:00Z", "endTime": "2026-05-31T23:10:00Z", "stage": "AWAKE"},
          {"startTime": "2026-05-31T23:10:00Z", "endTime": "2026-06-01T01:10:00Z", "stage": "LIGHT"},
          {"startTime": "2026-06-01T01:10:00Z", "endTime": "2026-06-01T02:40:00Z", "stage": "DEEP"},
          {"startTime": "2026-06-01T02:40:00Z", "endTime": "2026-06-01T03:00:00Z", "stage": "AWAKE"},
          {"startTime": "2026-06-01T03:00:00Z", "endTime": "2026-06-01T05:00:00Z", "stage": "LIGHT"},
          {"startTime": "2026-06-01T05:00:00Z", "endTime": "2026-06-01T06:50:00Z", "stage": "REM"},
          {"startTime": "2026-06-01T06:50:00Z", "endTime": "2026-06-01T07:00:00Z", "stage": "AWAKE"}
        ]
      }
    }
  ]
}
```

`backend/tests/fixtures/googlehealth/sleep_no_stages.json`:
```json
{
  "dataPoints": [
    {
      "name": "users/me/dataTypes/sleep/dataPoints/n2",
      "sleep": {
        "session": {
          "startTime": "2026-06-01T23:30:00Z",
          "endTime": "2026-06-02T06:30:00Z"
        },
        "sleepMetadata": {"stagesState": "STAGES_UNAVAILABLE"},
        "sleepSummary": {"totalDuration": "25200s"}
      }
    }
  ]
}
```

- [ ] **Step 2: Write the failing test**

`backend/tests/biomarkers/test_parser_sleep.py`:
```python
import json
from datetime import date
from pathlib import Path

import pytest

from bioage.biomarkers.parsers.sleep import parse_sleep

FIXTURES = Path(__file__).parent.parent / "fixtures" / "googlehealth"


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture
def night():
    return load("sleep")["dataPoints"][0]


def test_sleep_is_dated_to_the_wake_date(night):
    parsed = parse_sleep(night)
    assert parsed is not None
    assert parsed.day == date(2026, 6, 1)


def test_total_duration_is_converted_to_minutes(night):
    parsed = parse_sleep(night)
    assert parsed is not None
    assert parsed.values["sleep_total_min"] == pytest.approx(480.0)


def test_efficiency_is_asleep_over_time_in_bed(night):
    # asleep = LIGHT 14400 + DEEP 5400 + REM 6600 = 26400s = 440 min
    # time in bed = 23:00 -> 07:00 = 480 min
    parsed = parse_sleep(night)
    assert parsed is not None
    assert parsed.values["sleep_efficiency_pct"] == pytest.approx(440 / 480 * 100)


def test_waso_excludes_leading_and_trailing_wakefulness(night):
    """Only the 02:40-03:00 awake block counts; the 10-minute blocks at each end do not."""
    parsed = parse_sleep(night)
    assert parsed is not None
    assert parsed.values["waso_min"] == pytest.approx(20.0)


def test_stage_percentages_are_fractions_of_time_asleep(night):
    parsed = parse_sleep(night)
    assert parsed is not None
    assert parsed.values["deep_pct"] == pytest.approx(5400 / 26400 * 100)
    assert parsed.values["rem_pct"] == pytest.approx(6600 / 26400 * 100)


def test_midpoint_is_minutes_past_midnight(night):
    # 23:00 -> 07:00, midpoint 03:00 = 180 minutes past midnight
    parsed = parse_sleep(night)
    assert parsed is not None
    assert parsed.values["sleep_midpoint_local_min"] == pytest.approx(180.0)


def test_midpoint_handles_a_session_entirely_after_midnight():
    point = {
        "sleep": {
            "session": {
                "startTime": "2026-06-01T01:00:00Z",
                "endTime": "2026-06-01T09:00:00Z",
            },
            "sleepMetadata": {"stagesState": "STAGES_UNAVAILABLE"},
            "sleepSummary": {"totalDuration": "28800s"},
        }
    }
    parsed = parse_sleep(point)
    assert parsed is not None
    assert parsed.values["sleep_midpoint_local_min"] == pytest.approx(300.0)


def test_night_without_stages_yields_duration_but_no_stage_fields():
    point = load("sleep_no_stages")["dataPoints"][0]
    parsed = parse_sleep(point)
    assert parsed is not None
    assert parsed.values["sleep_total_min"] == pytest.approx(420.0)
    assert "deep_pct" not in parsed.values
    assert "rem_pct" not in parsed.values
    assert "waso_min" not in parsed.values
    assert "sleep_efficiency_pct" not in parsed.values


def test_returns_none_for_a_non_sleep_payload():
    assert parse_sleep({"steps": {}}) is None


def test_returns_none_when_the_session_is_missing():
    assert parse_sleep({"sleep": {"sleepSummary": {"totalDuration": "100s"}}}) is None


def test_zero_length_session_does_not_divide_by_zero():
    point = {
        "sleep": {
            "session": {
                "startTime": "2026-06-01T01:00:00Z",
                "endTime": "2026-06-01T01:00:00Z",
            },
            "sleepMetadata": {"stagesState": "STAGES_AVAILABLE"},
            "sleepSummary": {
                "totalDuration": "0s",
                "stageSummary": [{"stage": "LIGHT", "duration": "0s"}],
            },
        }
    }
    assert parse_sleep(point) is None


def test_all_awake_night_yields_zero_efficiency_not_a_crash():
    point = {
        "sleep": {
            "session": {
                "startTime": "2026-06-01T01:00:00Z",
                "endTime": "2026-06-01T03:00:00Z",
            },
            "sleepMetadata": {"stagesState": "STAGES_AVAILABLE"},
            "sleepSummary": {
                "totalDuration": "7200s",
                "stageSummary": [{"stage": "AWAKE", "duration": "7200s"}],
            },
            "sleepStages": [
                {"startTime": "2026-06-01T01:00:00Z", "endTime": "2026-06-01T03:00:00Z",
                 "stage": "AWAKE"}
            ],
        }
    }
    parsed = parse_sleep(point)
    assert parsed is not None
    assert parsed.values["sleep_efficiency_pct"] == pytest.approx(0.0)
    assert "deep_pct" not in parsed.values
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/biomarkers/test_parser_sleep.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bioage.biomarkers.parsers.sleep'`

- [ ] **Step 4: Implement the sleep parser**

`backend/src/bioage/biomarkers/parsers/sleep.py`:
```python
"""Sleep parsing, including the metrics the API does not provide directly.

The Sleep message carries a session interval, a total duration, per-stage durations and
a stage timeline. Sleep efficiency and WASO are *not* fields; both are derived here:

    time_in_bed = session.end - session.start
    asleep      = LIGHT + DEEP + REM
    efficiency  = asleep / time_in_bed * 100
    WASO        = AWAKE stages strictly between the first and last non-awake stage

Leading and trailing wakefulness is time in bed awake, not wakefulness *after sleep
onset*, so it is excluded from WASO by definition.

A night is attributed to its wake date, the conventional attribution for sleep.
"""

from __future__ import annotations

from bioage.biomarkers.parsers.common import (
    parse_duration_seconds,
    parse_timestamp,
)
from bioage.biomarkers.parsers.daily import ParsedPoint

ASLEEP_STAGES = ("LIGHT", "DEEP", "REM")


def parse_sleep(payload: dict) -> ParsedPoint | None:
    body = payload.get("sleep")
    if not isinstance(body, dict):
        return None

    session = body.get("session")
    if not isinstance(session, dict) or "startTime" not in session or "endTime" not in session:
        return None

    start = parse_timestamp(session["startTime"])
    end = parse_timestamp(session["endTime"])
    time_in_bed_min = (end - start).total_seconds() / 60.0
    if time_in_bed_min <= 0:
        return None

    summary = body.get("sleepSummary") or {}
    total_raw = summary.get("totalDuration")
    total_min = parse_duration_seconds(total_raw) / 60.0 if total_raw else time_in_bed_min

    midpoint = start + (end - start) / 2
    values: dict[str, float] = {
        "sleep_total_min": total_min,
        "sleep_midpoint_local_min": midpoint.hour * 60.0 + midpoint.minute + midpoint.second / 60.0,
    }

    stages_available = (body.get("sleepMetadata") or {}).get("stagesState") == "STAGES_AVAILABLE"
    stage_summary = summary.get("stageSummary")
    if stages_available and isinstance(stage_summary, list):
        durations: dict[str, float] = {}
        for entry in stage_summary:
            stage = entry.get("stage")
            duration = entry.get("duration")
            if stage and duration:
                durations[stage] = durations.get(stage, 0.0) + parse_duration_seconds(duration)

        asleep_seconds = sum(durations.get(stage, 0.0) for stage in ASLEEP_STAGES)
        values["sleep_efficiency_pct"] = asleep_seconds / 60.0 / time_in_bed_min * 100.0

        if asleep_seconds > 0:
            values["deep_pct"] = durations.get("DEEP", 0.0) / asleep_seconds * 100.0
            values["rem_pct"] = durations.get("REM", 0.0) / asleep_seconds * 100.0
            waso = _waso_minutes(body.get("sleepStages"))
            if waso is not None:
                values["waso_min"] = waso

    return ParsedPoint(end.date(), values)


def _waso_minutes(stages: object) -> float | None:
    """Sum AWAKE stages lying strictly between the first and last non-awake stage."""
    if not isinstance(stages, list) or not stages:
        return None

    asleep_indices = [
        index for index, stage in enumerate(stages) if stage.get("stage") in ASLEEP_STAGES
    ]
    if not asleep_indices:
        return None

    first, last = asleep_indices[0], asleep_indices[-1]
    total = 0.0
    for stage in stages[first:last + 1]:
        if stage.get("stage") != "AWAKE":
            continue
        start = parse_timestamp(stage["startTime"])
        end = parse_timestamp(stage["endTime"])
        total += (end - start).total_seconds() / 60.0
    return total
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/biomarkers/test_parser_sleep.py -v`
Expected: PASS — 12 passed

- [ ] **Step 6: Commit**

```bash
git add backend/src/bioage/biomarkers/parsers/sleep.py \
        backend/tests/fixtures/googlehealth/sleep.json \
        backend/tests/fixtures/googlehealth/sleep_no_stages.json \
        backend/tests/biomarkers/test_parser_sleep.py
git commit -m "feat: sleep parser deriving efficiency, WASO and midpoint from stage data"
```

---

### Task 14: Sleep regularity via circular statistics

**Files:**
- Create: `backend/src/bioage/biomarkers/regularity.py`
- Create: `backend/tests/biomarkers/test_regularity.py`

**Interfaces:**
- Consumes: nothing
- Produces: `sleep_regularity_minutes(midpoints_min: Sequence[float]) -> float | None` — circular standard deviation of sleep midpoints, in minutes. `None` for fewer than 3 values.

> A plain standard deviation is wrong here. Midpoints of 23:50 and 00:10 are 20 minutes
> apart, but as raw minute values (1430 and 10) they look 1420 apart. Treating the clock
> as a circle is required for correctness, not elegance.

- [ ] **Step 1: Write the failing test**

`backend/tests/biomarkers/test_regularity.py`:
```python
import pytest

from bioage.biomarkers.regularity import sleep_regularity_minutes

MINUTES_PER_DAY = 1440


def test_returns_none_for_too_few_nights():
    assert sleep_regularity_minutes([180.0, 190.0]) is None


def test_identical_midpoints_have_zero_variability():
    assert sleep_regularity_minutes([180.0] * 10) == pytest.approx(0.0, abs=1e-9)


def test_midpoints_straddling_midnight_are_treated_as_close_together():
    """23:50, 00:00 and 00:10 are 20 minutes apart in total, not 1420."""
    straddling = [1430.0, 0.0, 10.0]
    assert sleep_regularity_minutes(straddling) < 30.0


def test_naive_standard_deviation_would_be_wrong_here():
    """Guard against a future 'simplification' to statistics.stdev."""
    import statistics

    straddling = [1430.0, 0.0, 10.0]
    naive = statistics.stdev(straddling)
    circular = sleep_regularity_minutes(straddling)
    assert circular is not None
    assert naive > 500.0
    assert circular < 30.0


def test_more_scattered_midpoints_give_larger_variability():
    tight = sleep_regularity_minutes([180.0, 185.0, 175.0, 182.0, 178.0])
    loose = sleep_regularity_minutes([120.0, 300.0, 60.0, 400.0, 200.0])
    assert tight is not None and loose is not None
    assert tight < loose


def test_result_is_never_negative():
    assert sleep_regularity_minutes([0.0, 720.0, 1439.0]) >= 0.0


def test_maximally_scattered_midpoints_do_not_exceed_a_quarter_day():
    """Circular SD saturates; it must not blow up past a physically meaningful bound."""
    scattered = [i * MINUTES_PER_DAY / 12 for i in range(12)]
    result = sleep_regularity_minutes(scattered)
    assert result is not None
    assert result <= MINUTES_PER_DAY / 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/biomarkers/test_regularity.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bioage.biomarkers.regularity'`

- [ ] **Step 3: Implement circular SD**

`backend/src/bioage/biomarkers/regularity.py`:
```python
"""Sleep regularity as the circular standard deviation of sleep midpoints.

Clock times live on a circle. Midpoints of 23:50 and 00:10 differ by 20 minutes, but as
raw minute-of-day values (1430 and 10) a linear standard deviation reports a difference
of 1420. Mapping each time to a unit vector and taking the resultant length gives the
standard circular SD:

    R     = |mean(exp(i * theta))|
    SD    = sqrt(-2 * ln(R))        (in radians)

which is then converted back to minutes.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

MINUTES_PER_DAY = 1440.0
MIN_NIGHTS = 3


def sleep_regularity_minutes(midpoints_min: Sequence[float]) -> float | None:
    """Circular standard deviation of sleep midpoints, in minutes.

    Larger values mean a more irregular sleep schedule. Returns None below MIN_NIGHTS,
    where the statistic is not meaningful.
    """
    if len(midpoints_min) < MIN_NIGHTS:
        return None

    angles = [2.0 * math.pi * (m % MINUTES_PER_DAY) / MINUTES_PER_DAY for m in midpoints_min]
    mean_cos = sum(math.cos(a) for a in angles) / len(angles)
    mean_sin = sum(math.sin(a) for a in angles) / len(angles)
    resultant = math.hypot(mean_cos, mean_sin)

    if resultant <= 0.0:
        # Perfectly uniform around the clock: maximal irregularity.
        return MINUTES_PER_DAY / 2.0
    if resultant >= 1.0:
        return 0.0

    sd_radians = math.sqrt(-2.0 * math.log(resultant))
    sd_minutes = sd_radians * MINUTES_PER_DAY / (2.0 * math.pi)
    return min(sd_minutes, MINUTES_PER_DAY / 2.0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/biomarkers/test_regularity.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/src/bioage/biomarkers/regularity.py backend/tests/biomarkers/test_regularity.py
git commit -m "feat: sleep regularity via circular standard deviation of midpoints"
```

---

### Task 15: Rolling-window feature computation

**Files:**
- Create: `backend/src/bioage/biomarkers/features.py`
- Create: `backend/tests/biomarkers/test_features.py`

**Interfaces:**
- Consumes: `bioage.biomarkers.regularity.sleep_regularity_minutes`, `bioage.types.Sex`, `bioage.estimators.models.BiomarkerVector`
- Produces:
  - `DailyRecord` — frozen dataclass mirroring `DailyMetric` fields, all `float | None` except `day: date`
  - `WindowCoverage` — frozen dataclass: `total_days`, `rhr_days`, `hrv_days`, `steps_days`, `sleep_days`
  - `WINDOW_DAYS = 30`, `MIN_WINDOW_DAYS = 14`, `LOW_CONFIDENCE_DAYS = 21`
  - `MIN_RHR_DAYS = 10`, `MIN_HRV_DAYS = 10`, `MIN_STEPS_DAYS = 14`, `MIN_SLEEP_DAYS = 10`
  - `window_records(records, window_end: date) -> list[DailyRecord]`
  - `compute_coverage(window: Sequence[DailyRecord]) -> WindowCoverage`
  - `build_vector(window, chronological_age, sex, height_m, weight_kg, waist_cm) -> BiomarkerVector | None`

- [ ] **Step 1: Write the failing test**

`backend/tests/biomarkers/test_features.py`:
```python
from datetime import date, timedelta

import pytest

from bioage.biomarkers.features import (
    LOW_CONFIDENCE_DAYS,
    MIN_WINDOW_DAYS,
    WINDOW_DAYS,
    DailyRecord,
    build_vector,
    compute_coverage,
    window_records,
)
from bioage.types import Sex


def make_records(n: int, end: date = date(2026, 7, 1), **overrides) -> list[DailyRecord]:
    """n consecutive days ending the day before `end`."""
    return [
        DailyRecord(
            day=end - timedelta(days=i + 1),
            resting_hr_bpm=overrides.get("resting_hr_bpm", 60.0),
            hrv_rmssd_ms=overrides.get("hrv_rmssd_ms", 45.0),
            steps=overrides.get("steps", 9000.0),
            sleep_efficiency_pct=overrides.get("sleep_efficiency_pct", 90.0),
            sleep_midpoint_local_min=overrides.get("sleep_midpoint_local_min", 180.0),
            active_zone_minutes=overrides.get("active_zone_minutes", 25.0),
        )
        for i in range(n)
    ]


def test_window_includes_only_the_trailing_30_days():
    records = make_records(60)
    window = window_records(records, window_end=date(2026, 7, 1))
    assert len(window) == WINDOW_DAYS
    assert min(r.day for r in window) == date(2026, 7, 1) - timedelta(days=WINDOW_DAYS)


def test_window_excludes_days_on_or_after_the_end_date():
    records = make_records(40) + [DailyRecord(day=date(2026, 7, 5), resting_hr_bpm=99.0)]
    window = window_records(records, window_end=date(2026, 7, 1))
    assert all(r.day < date(2026, 7, 1) for r in window)


def test_coverage_counts_days_per_biomarker():
    records = make_records(30)
    records[0] = DailyRecord(day=records[0].day, resting_hr_bpm=None, steps=9000.0)
    coverage = compute_coverage(records)
    assert coverage.total_days == 30
    assert coverage.rhr_days == 29
    assert coverage.steps_days == 30


def test_vector_uses_medians_not_means():
    """One absurd day must not move the estimate; that is why medians are used."""
    records = make_records(30)
    records[0] = DailyRecord(day=records[0].day, resting_hr_bpm=200.0, steps=9000.0)
    vector = build_vector(
        records, chronological_age=40.0, sex=Sex.MALE,
        height_m=1.78, weight_kg=74.0, waist_cm=88.0,
    )
    assert vector is not None
    assert vector.resting_hr_bpm == pytest.approx(60.0)


def test_vector_computes_bmi_from_height_and_weight():
    vector = build_vector(
        make_records(30), chronological_age=40.0, sex=Sex.MALE,
        height_m=1.80, weight_kg=81.0, waist_cm=88.0,
    )
    assert vector is not None
    assert vector.bmi == pytest.approx(25.0)


def test_vector_bmi_is_none_without_height():
    vector = build_vector(
        make_records(30), chronological_age=40.0, sex=Sex.MALE,
        height_m=None, weight_kg=81.0, waist_cm=88.0,
    )
    assert vector is not None
    assert vector.bmi is None


def test_vector_is_none_below_the_minimum_window():
    records = make_records(MIN_WINDOW_DAYS - 1)
    assert build_vector(
        records, chronological_age=40.0, sex=Sex.MALE,
        height_m=1.78, weight_kg=74.0, waist_cm=88.0,
    ) is None


def test_vector_exists_exactly_at_the_minimum_window():
    records = make_records(MIN_WINDOW_DAYS)
    assert build_vector(
        records, chronological_age=40.0, sex=Sex.MALE,
        height_m=1.78, weight_kg=74.0, waist_cm=88.0,
    ) is not None


def test_biomarker_below_its_own_minimum_is_dropped_from_the_vector():
    """20 days of data but only 5 nights of HRV: HRV must not participate."""
    records = make_records(20)
    thinned = [
        DailyRecord(
            day=r.day,
            resting_hr_bpm=r.resting_hr_bpm,
            hrv_rmssd_ms=r.hrv_rmssd_ms if i < 5 else None,
            steps=r.steps,
            sleep_efficiency_pct=r.sleep_efficiency_pct,
            sleep_midpoint_local_min=r.sleep_midpoint_local_min,
        )
        for i, r in enumerate(records)
    ]
    vector = build_vector(
        thinned, chronological_age=40.0, sex=Sex.MALE,
        height_m=1.78, weight_kg=74.0, waist_cm=88.0,
    )
    assert vector is not None
    assert vector.hrv_rmssd_ms is None
    assert vector.resting_hr_bpm is not None


def test_regularity_is_computed_from_midpoints():
    records = make_records(30)
    vector = build_vector(
        records, chronological_age=40.0, sex=Sex.MALE,
        height_m=1.78, weight_kg=74.0, waist_cm=88.0,
    )
    assert vector is not None
    assert vector.sleep_regularity_min == pytest.approx(0.0, abs=1e-6)


def test_coverage_flags_low_confidence_below_the_threshold():
    assert compute_coverage(make_records(LOW_CONFIDENCE_DAYS - 1)).is_low_confidence is True
    assert compute_coverage(make_records(WINDOW_DAYS)).is_low_confidence is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/biomarkers/test_features.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bioage.biomarkers.features'`

- [ ] **Step 3: Implement features**

`backend/src/bioage/biomarkers/features.py`:
```python
"""Rolling-window feature computation.

Pure: takes daily records and profile scalars, returns a BiomarkerVector. Medians rather
than means throughout, because a single mis-measured night should not move a 30-day
estimate.

Two levels of gating apply. The window as a whole needs MIN_WINDOW_DAYS of data to
produce anything. Each biomarker additionally needs its own minimum number of days, so a
month with only five HRV nights does not contribute a confident-looking HRV age.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from bioage.biomarkers.regularity import sleep_regularity_minutes
from bioage.estimators.models import BiomarkerVector
from bioage.types import Sex

WINDOW_DAYS = 30
MIN_WINDOW_DAYS = 14
LOW_CONFIDENCE_DAYS = 21

MIN_RHR_DAYS = 10
MIN_HRV_DAYS = 10
MIN_STEPS_DAYS = 14
MIN_SLEEP_DAYS = 10


@dataclass(frozen=True)
class DailyRecord:
    day: date
    resting_hr_bpm: float | None = None
    hrv_rmssd_ms: float | None = None
    steps: float | None = None
    active_zone_minutes: float | None = None
    sleep_efficiency_pct: float | None = None
    sleep_midpoint_local_min: float | None = None
    respiratory_rate_brpm: float | None = None


@dataclass(frozen=True)
class WindowCoverage:
    total_days: int
    rhr_days: int
    hrv_days: int
    steps_days: int
    sleep_days: int

    @property
    def is_low_confidence(self) -> bool:
        return self.total_days < LOW_CONFIDENCE_DAYS

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "total_days": self.total_days,
            "rhr_days": self.rhr_days,
            "hrv_days": self.hrv_days,
            "steps_days": self.steps_days,
            "sleep_days": self.sleep_days,
            "is_low_confidence": self.is_low_confidence,
        }


def window_records(
    records: Sequence[DailyRecord],
    window_end: date,
    window_days: int = WINDOW_DAYS,
) -> list[DailyRecord]:
    """Records in the half-open interval [window_end - window_days, window_end)."""
    start = window_end - timedelta(days=window_days)
    return [r for r in records if start <= r.day < window_end]


def _values(window: Sequence[DailyRecord], attribute: str) -> list[float]:
    return [
        value for r in window if (value := getattr(r, attribute)) is not None
    ]


def _median_if_enough(
    window: Sequence[DailyRecord], attribute: str, minimum: int
) -> float | None:
    values = _values(window, attribute)
    return statistics.median(values) if len(values) >= minimum else None


def compute_coverage(window: Sequence[DailyRecord]) -> WindowCoverage:
    return WindowCoverage(
        total_days=len(window),
        rhr_days=len(_values(window, "resting_hr_bpm")),
        hrv_days=len(_values(window, "hrv_rmssd_ms")),
        steps_days=len(_values(window, "steps")),
        sleep_days=len(_values(window, "sleep_efficiency_pct")),
    )


def build_vector(
    window: Sequence[DailyRecord],
    chronological_age: float,
    sex: Sex,
    height_m: float | None,
    weight_kg: float | None,
    waist_cm: float | None,
) -> BiomarkerVector | None:
    """Aggregate a window into a BiomarkerVector, or None if the window is too thin."""
    if len(window) < MIN_WINDOW_DAYS:
        return None

    bmi = None
    if height_m and weight_kg and height_m > 0:
        bmi = weight_kg / (height_m**2)

    midpoints = _values(window, "sleep_midpoint_local_min")

    return BiomarkerVector(
        chronological_age=chronological_age,
        sex=sex,
        resting_hr_bpm=_median_if_enough(window, "resting_hr_bpm", MIN_RHR_DAYS),
        hrv_rmssd_ms=_median_if_enough(window, "hrv_rmssd_ms", MIN_HRV_DAYS),
        mean_daily_steps=_median_if_enough(window, "steps", MIN_STEPS_DAYS),
        sleep_efficiency_pct=_median_if_enough(window, "sleep_efficiency_pct", MIN_SLEEP_DAYS),
        sleep_regularity_min=sleep_regularity_minutes(midpoints),
        bmi=bmi,
        waist_cm=waist_cm,
        active_zone_minutes_per_day=_median_if_enough(window, "active_zone_minutes", 1),
        respiratory_rate_brpm=_median_if_enough(window, "respiratory_rate_brpm", 1),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/biomarkers/test_features.py -v`
Expected: PASS — 11 passed

- [ ] **Step 5: Type-check and verify purity**

Run:
```bash
cd backend
uv run mypy src/bioage/biomarkers
! grep -rnE "from bioage\.(db|api|ingest)" src/bioage/biomarkers/features.py \
  && echo "features are pure"
```
Expected: `Success: no issues found` then `features are pure`

- [ ] **Step 6: Commit**

```bash
git add backend/src/bioage/biomarkers/features.py backend/tests/biomarkers/test_features.py
git commit -m "feat: rolling-window feature aggregation with per-biomarker coverage gating"
```

---

## Phase E — Scoring

### Task 16: As-of profile resolution

**Files:**
- Create: `backend/src/bioage/profile.py`
- Create: `backend/tests/test_profile.py`

**Interfaces:**
- Consumes: `bioage.db.models.Profile`, `bioage.db.models.Measurement`, `bioage.db.models.DailyMetric`
- Produces:
  - `ResolvedProfile` — frozen dataclass: `sex: Sex`, `birthdate: date`, `height_m: float | None`, `weight_kg: float | None`, `waist_cm: float | None`
  - `age_on(birthdate: date, day: date) -> float` — age in years including the fractional part
  - `resolve_profile(session, as_of: date) -> ResolvedProfile | None`

> Manual measurements take precedence over anything the API supplied. An API-sourced
> weight or height is used only when no manual measurement exists on or before `as_of`.
> Waist is never available from the API.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_profile.py`:
```python
from datetime import date

import pytest

from bioage.db.models import DailyMetric, Measurement, Profile
from bioage.profile import age_on, resolve_profile
from bioage.types import Sex


@pytest.fixture
def seeded(db):
    db.add(Profile(id=1, sex=Sex.MALE, birthdate=date(1990, 1, 1)))
    db.flush()
    return db


def test_age_on_includes_the_fractional_year():
    assert age_on(date(1990, 1, 1), date(2026, 7, 2)) == pytest.approx(36.5, abs=0.02)


def test_age_on_is_exact_on_a_birthday():
    assert age_on(date(1990, 1, 1), date(2026, 1, 1)) == pytest.approx(36.0, abs=0.01)


def test_returns_none_when_no_profile_exists(db):
    assert resolve_profile(db, as_of=date(2026, 7, 1)) is None


def test_uses_the_latest_measurement_on_or_before_the_date(seeded):
    seeded.add_all([
        Measurement(kind="waist_cm", value=92.0, measured_on=date(2026, 1, 1)),
        Measurement(kind="waist_cm", value=88.0, measured_on=date(2026, 6, 1)),
    ])
    seeded.flush()
    assert resolve_profile(seeded, as_of=date(2026, 7, 1)).waist_cm == pytest.approx(88.0)


def test_ignores_measurements_taken_after_the_date(seeded):
    """A waist measured in July must not rewrite a score for a week in May."""
    seeded.add_all([
        Measurement(kind="waist_cm", value=92.0, measured_on=date(2026, 1, 1)),
        Measurement(kind="waist_cm", value=80.0, measured_on=date(2026, 7, 1)),
    ])
    seeded.flush()
    assert resolve_profile(seeded, as_of=date(2026, 5, 1)).waist_cm == pytest.approx(92.0)


def test_waist_is_none_when_never_measured(seeded):
    assert resolve_profile(seeded, as_of=date(2026, 7, 1)).waist_cm is None


def test_falls_back_to_api_weight_when_no_manual_measurement(seeded):
    seeded.add(DailyMetric(date=date(2026, 6, 15), weight_kg=76.5))
    seeded.flush()
    assert resolve_profile(seeded, as_of=date(2026, 7, 1)).weight_kg == pytest.approx(76.5)


def test_manual_weight_takes_precedence_over_api_weight(seeded):
    seeded.add(DailyMetric(date=date(2026, 6, 15), weight_kg=76.5))
    seeded.add(Measurement(kind="weight_kg", value=74.0, measured_on=date(2026, 6, 1)))
    seeded.flush()
    assert resolve_profile(seeded, as_of=date(2026, 7, 1)).weight_kg == pytest.approx(74.0)


def test_manual_weight_wins_even_when_the_api_value_is_more_recent(seeded):
    seeded.add(DailyMetric(date=date(2026, 6, 30), weight_kg=76.5))
    seeded.add(Measurement(kind="weight_kg", value=74.0, measured_on=date(2026, 1, 1)))
    seeded.flush()
    assert resolve_profile(seeded, as_of=date(2026, 7, 1)).weight_kg == pytest.approx(74.0)


def test_resolves_sex_and_birthdate(seeded):
    resolved = resolve_profile(seeded, as_of=date(2026, 7, 1))
    assert resolved.sex is Sex.MALE
    assert resolved.birthdate == date(1990, 1, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_profile.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bioage.profile'`

- [ ] **Step 3: Implement profile resolution**

`backend/src/bioage/profile.py`:
```python
"""Resolve the subject's profile as it stood on a given date.

Weekly scores are computed for past weeks, so the profile must be resolved *as of* that
week rather than from today's values. Otherwise re-measuring your waist in July would
silently rewrite every score back to May.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from bioage.db.models import DailyMetric, Measurement, Profile
from bioage.types import Sex

DAYS_PER_YEAR = 365.2425


@dataclass(frozen=True)
class ResolvedProfile:
    sex: Sex
    birthdate: date
    height_m: float | None
    weight_kg: float | None
    waist_cm: float | None


def age_on(birthdate: date, day: date) -> float:
    """Chronological age in years, including the fractional part."""
    return (day - birthdate).days / DAYS_PER_YEAR


def _latest_measurement(session: Session, kind: str, as_of: date) -> float | None:
    stmt = (
        select(Measurement.value)
        .where(Measurement.kind == kind, Measurement.measured_on <= as_of)
        .order_by(Measurement.measured_on.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def _latest_api_value(session: Session, column, as_of: date) -> float | None:
    stmt = (
        select(column)
        .where(column.isnot(None), DailyMetric.date <= as_of)
        .order_by(DailyMetric.date.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def resolve_profile(session: Session, as_of: date) -> ResolvedProfile | None:
    profile = session.get(Profile, 1)
    if profile is None:
        return None

    # Manual measurements always win; API values only fill gaps.
    height = _latest_measurement(session, "height_m", as_of)
    if height is None:
        height = _latest_api_value(session, DailyMetric.height_m, as_of)

    weight = _latest_measurement(session, "weight_kg", as_of)
    if weight is None:
        weight = _latest_api_value(session, DailyMetric.weight_kg, as_of)

    return ResolvedProfile(
        sex=profile.sex,
        birthdate=profile.birthdate,
        height_m=height,
        weight_kg=weight,
        waist_cm=_latest_measurement(session, "waist_cm", as_of),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_profile.py -v`
Expected: PASS — 10 passed

- [ ] **Step 5: Commit**

```bash
git add backend/src/bioage/profile.py backend/tests/test_profile.py
git commit -m "feat: as-of profile resolution with manual-over-API precedence"
```

---

### Task 17: Weekly scoring pipeline

**Files:**
- Create: `backend/src/bioage/scoring.py`
- Create: `backend/tests/test_scoring.py`

**Interfaces:**
- Consumes: `features`, `composite.estimate_all`, `profile.resolve_profile`, `db.models`
- Produces:
  - `iso_week_starts(first_day: date, last_day: date) -> list[date]` — Mondays
  - `load_daily_records(session) -> list[DailyRecord]`
  - `score_week(session, week_start: date) -> BioAgeScore | None`
  - `rescore_all(session) -> int` — returns the number of weeks written; idempotent

- [ ] **Step 1: Write the failing test**

`backend/tests/test_scoring.py`:
```python
from datetime import date, timedelta

import pytest

from bioage.db.models import BioAgeScore, DailyMetric, Measurement, Profile
from bioage.scoring import iso_week_starts, rescore_all, score_week
from bioage.types import Sex


@pytest.fixture
def populated(db):
    db.add(Profile(id=1, sex=Sex.MALE, birthdate=date(1990, 1, 1)))
    db.add(Measurement(kind="height_m", value=1.78, measured_on=date(2026, 1, 1)))
    db.add(Measurement(kind="weight_kg", value=74.0, measured_on=date(2026, 1, 1)))
    db.add(Measurement(kind="waist_cm", value=88.0, measured_on=date(2026, 1, 1)))
    start = date(2026, 4, 1)
    for i in range(90):
        db.add(DailyMetric(
            date=start + timedelta(days=i),
            resting_hr_bpm=60.0,
            hrv_rmssd_ms=45.0,
            steps=9000,
            active_zone_minutes=25,
            sleep_efficiency_pct=90.0,
            sleep_midpoint_local_min=180.0,
        ))
    db.flush()
    return db


def test_iso_week_starts_are_mondays():
    weeks = iso_week_starts(date(2026, 4, 1), date(2026, 5, 1))
    assert all(w.weekday() == 0 for w in weeks)


def test_iso_week_starts_are_contiguous_and_ordered():
    weeks = iso_week_starts(date(2026, 4, 1), date(2026, 6, 1))
    assert weeks == sorted(weeks)
    for a, b in zip(weeks, weeks[1:]):
        assert (b - a).days == 7


def test_score_week_produces_a_composite_with_a_band(populated):
    score = score_week(populated, week_start=date(2026, 6, 1))
    assert score is not None
    assert score.ci_low < score.composite_age < score.ci_high
    assert score.chronological_age > 30


def test_score_week_records_its_components_and_coverage(populated):
    score = score_week(populated, week_start=date(2026, 6, 1))
    assert score is not None
    names = {c["component"] for c in score.components}
    assert "kdm" in names
    assert "ntnu_fitness" in names
    assert score.coverage["total_days"] > 0


def test_score_week_returns_none_before_any_data(populated):
    assert score_week(populated, week_start=date(2026, 1, 5)) is None


def test_thin_window_is_flagged_low_confidence_with_a_wider_band(db):
    db.add(Profile(id=1, sex=Sex.MALE, birthdate=date(1990, 1, 1)))
    db.add(Measurement(kind="height_m", value=1.78, measured_on=date(2026, 1, 1)))
    db.add(Measurement(kind="weight_kg", value=74.0, measured_on=date(2026, 1, 1)))
    db.add(Measurement(kind="waist_cm", value=88.0, measured_on=date(2026, 1, 1)))
    start = date(2026, 6, 1)
    for i in range(16):
        db.add(DailyMetric(
            date=start + timedelta(days=i), resting_hr_bpm=60.0, hrv_rmssd_ms=45.0,
            steps=9000, sleep_efficiency_pct=90.0, sleep_midpoint_local_min=180.0,
        ))
    db.flush()
    score = score_week(db, week_start=date(2026, 6, 22))
    assert score is not None
    assert score.is_low_confidence is True


def test_rescore_all_is_idempotent(populated):
    first = rescore_all(populated)
    populated.flush()
    rows_after_first = populated.query(BioAgeScore).count()
    second = rescore_all(populated)
    populated.flush()
    assert first == second
    assert populated.query(BioAgeScore).count() == rows_after_first


def test_rescore_all_overwrites_rather_than_duplicating(populated):
    rescore_all(populated)
    populated.flush()
    before = populated.query(BioAgeScore).order_by(BioAgeScore.week_start).first()
    populated.query(DailyMetric).update({DailyMetric.resting_hr_bpm: 80.0})
    populated.flush()
    rescore_all(populated)
    populated.flush()
    after = populated.query(BioAgeScore).order_by(BioAgeScore.week_start).first()
    assert after.week_start == before.week_start
    assert after.composite_age != pytest.approx(before.composite_age)


def test_a_healthier_profile_scores_younger(db):
    def build(rhr: float, steps: int, rmssd: float) -> float:
        db.query(DailyMetric).delete()
        db.query(BioAgeScore).delete()
        db.merge(Profile(id=1, sex=Sex.MALE, birthdate=date(1990, 1, 1)))
        measurements = (("height_m", 1.78), ("weight_kg", 74.0), ("waist_cm", 88.0))
        for index, (kind, value) in enumerate(measurements, start=1):
            db.merge(Measurement(id=index, kind=kind, value=value,
                                 measured_on=date(2026, 1, 1)))
        for i in range(60):
            db.add(DailyMetric(
                date=date(2026, 4, 1) + timedelta(days=i), resting_hr_bpm=rhr,
                hrv_rmssd_ms=rmssd, steps=steps, sleep_efficiency_pct=90.0,
                sleep_midpoint_local_min=180.0,
            ))
        db.flush()
        score = score_week(db, week_start=date(2026, 5, 25))
        assert score is not None
        return score.composite_age

    fit = build(rhr=52.0, steps=13000, rmssd=65.0)
    unfit = build(rhr=78.0, steps=2500, rmssd=22.0)
    assert fit < unfit
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_scoring.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bioage.scoring'`

- [ ] **Step 3: Implement scoring**

`backend/src/bioage/scoring.py`:
```python
"""Weekly scoring orchestration.

For every ISO week covered by the data, build the trailing 30-day feature window,
resolve the profile as it stood that week, run every applicable estimator, and persist
the composite. Writes are upserts keyed on week_start, so rescoring is idempotent.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from bioage.biomarkers.features import (
    DailyRecord,
    build_vector,
    compute_coverage,
    window_records,
)
from bioage.db.models import BioAgeScore, DailyMetric
from bioage.estimators.composite import estimate_all
from bioage.profile import age_on, resolve_profile


def iso_week_starts(first_day: date, last_day: date) -> list[date]:
    """Every Monday from the week containing first_day through the week of last_day."""
    cursor = first_day - timedelta(days=first_day.weekday())
    weeks: list[date] = []
    while cursor <= last_day:
        weeks.append(cursor)
        cursor += timedelta(days=7)
    return weeks


def load_daily_records(session: Session) -> list[DailyRecord]:
    rows = session.execute(select(DailyMetric).order_by(DailyMetric.date)).scalars().all()
    return [
        DailyRecord(
            day=row.date,
            resting_hr_bpm=row.resting_hr_bpm,
            hrv_rmssd_ms=row.hrv_rmssd_ms,
            steps=float(row.steps) if row.steps is not None else None,
            active_zone_minutes=(
                float(row.active_zone_minutes) if row.active_zone_minutes is not None else None
            ),
            sleep_efficiency_pct=row.sleep_efficiency_pct,
            sleep_midpoint_local_min=row.sleep_midpoint_local_min,
            respiratory_rate_brpm=row.respiratory_rate_brpm,
        )
        for row in rows
    ]


def score_week(
    session: Session,
    week_start: date,
    records: list[DailyRecord] | None = None,
) -> BioAgeScore | None:
    """Compute and persist one week's score, or return None if it cannot be scored."""
    if records is None:
        records = load_daily_records(session)

    week_end = week_start + timedelta(days=7)
    window = window_records(records, window_end=week_end)
    if not window:
        return None

    profile = resolve_profile(session, as_of=week_end)
    if profile is None:
        return None

    chronological_age = age_on(profile.birthdate, week_end)
    vector = build_vector(
        window,
        chronological_age=chronological_age,
        sex=profile.sex,
        height_m=profile.height_m,
        weight_kg=profile.weight_kg,
        waist_cm=profile.waist_cm,
    )
    if vector is None:
        return None

    coverage = compute_coverage(window)
    composite = estimate_all(vector, low_confidence=coverage.is_low_confidence)
    if composite is None:
        return None

    score = session.get(BioAgeScore, week_start) or BioAgeScore(week_start=week_start)
    score.chronological_age = chronological_age
    score.composite_age = composite.age_years
    score.ci_low = composite.ci_low
    score.ci_high = composite.ci_high
    score.components = [asdict(c) for c in composite.components]
    score.coverage = coverage.as_dict()
    score.is_low_confidence = composite.is_low_confidence
    session.merge(score)
    return score


def rescore_all(session: Session) -> int:
    """Recompute every scorable week. Returns the number of weeks written."""
    records = load_daily_records(session)
    if not records:
        return 0

    days = [r.day for r in records]
    written = 0
    for week_start in iso_week_starts(min(days), max(days)):
        if score_week(session, week_start, records=records) is not None:
            written += 1
    return written
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_scoring.py -v`
Expected: PASS — 9 passed

- [ ] **Step 5: Commit**

```bash
git add backend/src/bioage/scoring.py backend/tests/test_scoring.py
git commit -m "feat: idempotent weekly scoring pipeline"
```

---

## Phase F — Demo data

### Task 18: Synthetic data generator and CLI

**Files:**
- Create: `backend/src/bioage/demo/__init__.py`
- Create: `backend/src/bioage/demo/generator.py`
- Create: `backend/src/bioage/cli.py`
- Create: `backend/tests/test_demo_generator.py`

**Interfaces:**
- Consumes: `db.models`, `scoring.rescore_all`
- Produces:
  - `generate_daily_metrics(start: date, days: int, seed: int = 20260802) -> list[DailyMetric]`
  - `seed_demo(session, days: int = 400, seed: int = 20260802) -> int`
  - CLI: `bioage seed-demo [--days N]`, `bioage rescore`, `bioage sync` (sync wired in Task 22)

> Determinism matters: the generator seeds an explicit `random.Random`, never the global
> RNG, so demo data and any test built on it are reproducible.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_demo_generator.py`:
```python
from datetime import date

import pytest

from bioage.db.models import BioAgeScore, DailyMetric, Profile
from bioage.demo.generator import generate_daily_metrics, seed_demo


def test_generator_is_deterministic_for_a_given_seed():
    a = generate_daily_metrics(date(2026, 1, 1), days=30, seed=7)
    b = generate_daily_metrics(date(2026, 1, 1), days=30, seed=7)
    assert [m.resting_hr_bpm for m in a] == [m.resting_hr_bpm for m in b]


def test_different_seeds_produce_different_data():
    a = generate_daily_metrics(date(2026, 1, 1), days=30, seed=7)
    b = generate_daily_metrics(date(2026, 1, 1), days=30, seed=8)
    assert [m.resting_hr_bpm for m in a] != [m.resting_hr_bpm for m in b]


def test_generates_the_requested_number_of_consecutive_days():
    metrics = generate_daily_metrics(date(2026, 1, 1), days=45)
    assert len(metrics) == 45
    assert metrics[0].date == date(2026, 1, 1)
    assert metrics[-1].date == date(2026, 2, 14)


def test_values_are_physiologically_plausible():
    for m in generate_daily_metrics(date(2026, 1, 1), days=200):
        assert 40 <= m.resting_hr_bpm <= 100
        assert 5 <= m.hrv_rmssd_ms <= 150
        assert 0 <= m.steps <= 40000
        assert 0 <= m.sleep_efficiency_pct <= 100
        assert 0 <= m.sleep_midpoint_local_min < 1440


def test_generator_leaves_realistic_gaps():
    """A real wearable is not worn every night; the demo must exercise gap handling."""
    metrics = generate_daily_metrics(date(2026, 1, 1), days=300)
    assert any(m.hrv_rmssd_ms is None for m in metrics)
    assert any(m.steps is not None for m in metrics)


def test_weekends_differ_from_weekdays():
    metrics = generate_daily_metrics(date(2026, 1, 1), days=200)
    weekday = [m.steps for m in metrics if m.date.weekday() < 5 and m.steps]
    weekend = [m.steps for m in metrics if m.date.weekday() >= 5 and m.steps]
    assert sum(weekday) / len(weekday) != pytest.approx(sum(weekend) / len(weekend), rel=0.01)


def test_seed_demo_populates_profile_metrics_and_scores(db):
    weeks = seed_demo(db, days=200)
    db.flush()
    assert db.query(Profile).count() == 1
    assert db.query(DailyMetric).count() == 200
    assert db.query(BioAgeScore).count() == weeks
    assert weeks > 20


def test_seed_demo_scores_have_valid_bands(db):
    seed_demo(db, days=200)
    db.flush()
    for score in db.query(BioAgeScore).all():
        assert score.ci_low < score.composite_age < score.ci_high
        assert 18.0 <= score.composite_age <= 100.0


def test_seed_demo_is_rerunnable(db):
    seed_demo(db, days=120)
    db.flush()
    first = db.query(DailyMetric).count()
    seed_demo(db, days=120)
    db.flush()
    assert db.query(DailyMetric).count() == first
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_demo_generator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bioage.demo'`

- [ ] **Step 3: Implement the generator**

`backend/src/bioage/demo/__init__.py`: empty file.

`backend/src/bioage/demo/generator.py`:
```python
"""Synthetic wearable history, so the application runs end-to-end without credentials.

The generator is deliberately not a toy: it produces weekday/weekend structure, slow
seasonal drift, day-to-day noise, and missing days, because those are exactly the
conditions the feature and scoring layers must survive.

It uses an explicit random.Random instance rather than the global RNG so that demo data
is reproducible and tests built on it are stable.
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

from sqlalchemy.orm import Session

from bioage.db.models import DailyMetric, Measurement, Profile
from bioage.scoring import rescore_all
from bioage.types import Sex

DEMO_SEED = 20260802
DEMO_BIRTHDATE = date(1990, 3, 14)


def generate_daily_metrics(
    start: date,
    days: int,
    seed: int = DEMO_SEED,
) -> list[DailyMetric]:
    """Produce `days` consecutive DailyMetric rows with realistic structure and gaps."""
    rng = random.Random(seed)
    metrics: list[DailyMetric] = []

    for offset in range(days):
        day = start + timedelta(days=offset)
        # Slow improvement over the year plus a seasonal wobble.
        trend = offset / max(days, 1)
        seasonal = math.sin(2 * math.pi * offset / 365.0)

        resting_hr = 62.0 - 4.0 * trend + 1.5 * seasonal + rng.gauss(0, 2.0)
        rmssd = 42.0 + 10.0 * trend + 3.0 * seasonal + rng.gauss(0, 6.0)

        is_weekend = day.weekday() >= 5
        base_steps = 11500 if is_weekend else 8800
        steps = base_steps * (1 + 0.15 * trend) + rng.gauss(0, 2200)

        azm = max(0, rng.gauss(24 + 10 * trend, 12))
        efficiency = min(99.0, max(60.0, rng.gauss(89.0 + 2.0 * trend, 3.5)))
        midpoint = (rng.gauss(200.0, 45.0)) % 1440.0

        # Realistic gaps: the band is not worn every night, and HRV needs sleep.
        wore_device = rng.random() > 0.06
        got_hrv = wore_device and rng.random() > 0.12

        metrics.append(DailyMetric(
            date=day,
            resting_hr_bpm=round(max(40.0, min(100.0, resting_hr)), 1) if wore_device else None,
            hrv_rmssd_ms=round(max(5.0, min(150.0, rmssd)), 1) if got_hrv else None,
            hrv_average_ms=round(max(5.0, min(150.0, rmssd * 0.92)), 1) if got_hrv else None,
            steps=int(max(0, min(40000, steps))) if wore_device else None,
            active_zone_minutes=int(azm) if wore_device else None,
            sleep_total_min=round(rng.gauss(432.0, 45.0), 1) if got_hrv else None,
            sleep_efficiency_pct=round(efficiency, 1) if got_hrv else None,
            waso_min=round(max(0.0, rng.gauss(24.0, 10.0)), 1) if got_hrv else None,
            deep_pct=round(max(5.0, rng.gauss(18.0, 4.0)), 1) if got_hrv else None,
            rem_pct=round(max(8.0, rng.gauss(22.0, 5.0)), 1) if got_hrv else None,
            sleep_midpoint_local_min=round(midpoint, 1) if got_hrv else None,
            respiratory_rate_brpm=round(rng.gauss(14.5, 0.9), 1) if got_hrv else None,
            spo2_pct=round(min(100.0, rng.gauss(96.3, 1.1)), 1) if got_hrv else None,
            skin_temp_delta_c=round(rng.gauss(0.0, 0.35), 2) if got_hrv else None,
        ))

    return metrics


def seed_demo(session: Session, days: int = 400, seed: int = DEMO_SEED) -> int:
    """Populate a demo profile, metrics and scores. Returns the number of weeks scored."""
    session.merge(Profile(id=1, sex=Sex.MALE, birthdate=DEMO_BIRTHDATE))

    start = date.today() - timedelta(days=days)
    for index, (kind, value) in enumerate(
        (("height_m", 1.78), ("weight_kg", 74.5), ("waist_cm", 87.0)), start=1
    ):
        session.merge(Measurement(id=index, kind=kind, value=value, measured_on=start))

    for metric in generate_daily_metrics(start, days=days, seed=seed):
        session.merge(metric)
    session.flush()

    return rescore_all(session)
```

- [ ] **Step 4: Implement the CLI**

`backend/src/bioage/cli.py`:
```python
"""Command-line entry points."""

from __future__ import annotations

import typer

from bioage.config import get_settings
from bioage.db.base import session_factory
from bioage.demo.generator import seed_demo
from bioage.scoring import rescore_all

app = typer.Typer(help="Fitbit Air biological age tooling.")


@app.command("seed-demo")
def seed_demo_command(days: int = 400) -> None:
    """Populate the database with synthetic history so the app runs without credentials."""
    with session_factory(get_settings().database_url)() as session:
        weeks = seed_demo(session, days=days)
        session.commit()
    typer.echo(f"Seeded {days} days of demo data and scored {weeks} weeks.")


@app.command("rescore")
def rescore_command() -> None:
    """Recompute every weekly score from the stored daily metrics."""
    with session_factory(get_settings().database_url)() as session:
        weeks = rescore_all(session)
        session.commit()
    typer.echo(f"Rescored {weeks} weeks.")


if __name__ == "__main__":
    app()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_demo_generator.py -v`
Expected: PASS — 9 passed

- [ ] **Step 6: Run the whole backend suite so far**

Run: `cd backend && uv run pytest -v`
Expected: PASS — all tests green

- [ ] **Step 7: Verify the demo end-to-end against the real database**

Run:
```bash
docker compose up -d db
cd backend
export DATABASE_URL=postgresql+psycopg://bioage:bioage@localhost:5432/bioage
uv run alembic upgrade head
uv run python -m bioage.cli seed-demo --days 400
```
Expected: `Seeded 400 days of demo data and scored NN weeks.` with NN above 50.

Then confirm the shape of the output:
```bash
docker compose exec db psql -U bioage -d bioage -c \
  "SELECT week_start, round(chronological_age::numeric,1) AS chrono, \
          round(composite_age::numeric,1) AS bio, is_low_confidence \
   FROM bioage_scores ORDER BY week_start LIMIT 5;"
```
Expected: five rows; early weeks flagged `t` for low confidence, `bio` within roughly 15 years of `chrono`. If biological ages are pinned at 18 or 100, the clamp is masking a units or sign error — stop and investigate before continuing.

- [ ] **Step 8: Commit**

```bash
git add backend/src/bioage/demo backend/src/bioage/cli.py backend/tests/test_demo_generator.py
git commit -m "feat: deterministic synthetic data generator and CLI"
```

---

## Phase G — Google Health ingestion

### Task 19: Data type registry

**Files:**
- Create: `backend/src/bioage/ingest/__init__.py`
- Create: `backend/src/bioage/ingest/registry.py`
- Create: `backend/tests/ingest/__init__.py`
- Create: `backend/tests/ingest/test_registry.py`

**Interfaces:**
- Consumes: all parsers
- Produces:
  - `DataTypeSpec` — frozen dataclass: `data_type_id: str`, `filter_field: str`, `max_window_days: int`, `scope: str`, `parser: Callable[[dict], ParsedPoint | None]`, `page_size: int`, `expected_empty: bool = False`
  - `DATA_TYPES: tuple[DataTypeSpec, ...]`, `SCOPES: tuple[str, ...]`, `get_spec(data_type_id: str) -> DataTypeSpec`

> The registry is the single place any Google-side constant appears. When Google changes
> a filter field name, exactly one line changes.

- [ ] **Step 1: Write the failing test**

`backend/tests/ingest/test_registry.py`:
```python
import pytest

from bioage.ingest.registry import DATA_TYPES, SCOPES, get_spec

METRICS_SCOPE = "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly"
ACTIVITY_SCOPE = "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly"
SLEEP_SCOPE = "https://www.googleapis.com/auth/googlehealth.sleep.readonly"


def test_steps_is_capped_at_fourteen_days():
    """The documented query range limit for steps is 14 days, unlike every other type."""
    assert get_spec("steps").max_window_days == 14


@pytest.mark.parametrize(
    "data_type",
    ["daily-resting-heart-rate", "daily-heart-rate-variability", "sleep",
     "daily-respiratory-rate", "daily-oxygen-saturation"],
)
def test_other_types_are_capped_at_ninety_days(data_type):
    assert get_spec(data_type).max_window_days == 90


def test_sleep_uses_the_documented_page_size_of_twenty_five():
    assert get_spec("sleep").page_size == 25


def test_every_spec_has_a_parser_and_a_scope():
    for spec in DATA_TYPES:
        assert callable(spec.parser)
        assert spec.scope.startswith("https://www.googleapis.com/auth/googlehealth.")


def test_scopes_are_exactly_the_three_documented_read_scopes():
    assert set(SCOPES) == {METRICS_SCOPE, ACTIVITY_SCOPE, SLEEP_SCOPE}


def test_data_type_ids_are_unique():
    ids = [s.data_type_id for s in DATA_TYPES]
    assert len(ids) == len(set(ids))


def test_vo2_max_is_registered_but_expected_empty():
    """The Air does not populate VO2max; polling it confirms that on the coverage table."""
    assert get_spec("daily-vo2-max").expected_empty is True


def test_get_spec_raises_for_an_unknown_type():
    with pytest.raises(KeyError):
        get_spec("not-a-real-type")


def test_the_registry_covers_every_biomarker_the_estimators_consume():
    ids = {s.data_type_id for s in DATA_TYPES}
    assert {"daily-resting-heart-rate", "daily-heart-rate-variability", "steps", "sleep"} <= ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/ingest/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bioage.ingest'`

- [ ] **Step 3: Implement the registry**

`backend/src/bioage/ingest/__init__.py`: empty file.

`backend/src/bioage/ingest/registry.py`:
```python
"""The single source of truth for every Google-side constant.

Each data type is described once: its path segment, the field its filter expression must
reference, its documented query-range cap, the OAuth scope it needs, and the parser that
turns its payload into daily values.

Filter field names must be confirmed against
https://developers.google.com/health/data-types at build time; the API launched in March
2026 and Google warned of breaking changes. Isolating them here means a change is a
one-line edit rather than a hunt through the codebase.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from bioage.biomarkers.parsers.daily import (
    ParsedPoint,
    parse_daily_heart_rate_variability,
    parse_daily_oxygen_saturation,
    parse_daily_respiratory_rate,
    parse_daily_resting_heart_rate,
    parse_daily_sleep_temperature_derivations,
)
from bioage.biomarkers.parsers.interval import parse_active_zone_minutes, parse_steps
from bioage.biomarkers.parsers.sample import parse_height, parse_weight
from bioage.biomarkers.parsers.sleep import parse_sleep

METRICS_SCOPE = (
    "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly"
)
ACTIVITY_SCOPE = "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly"
SLEEP_SCOPE = "https://www.googleapis.com/auth/googlehealth.sleep.readonly"

SCOPES = (METRICS_SCOPE, ACTIVITY_SCOPE, SLEEP_SCOPE)

DEFAULT_WINDOW_DAYS = 90
STEPS_WINDOW_DAYS = 14  # documented cap, unique to steps


def _noop(_: dict) -> ParsedPoint | None:
    return None


@dataclass(frozen=True)
class DataTypeSpec:
    data_type_id: str
    filter_field: str
    max_window_days: int
    scope: str
    parser: Callable[[dict], ParsedPoint | None]
    page_size: int = 1440
    expected_empty: bool = False


DATA_TYPES: tuple[DataTypeSpec, ...] = (
    DataTypeSpec(
        "daily-resting-heart-rate", "dailyRestingHeartRate.date",
        DEFAULT_WINDOW_DAYS, METRICS_SCOPE, parse_daily_resting_heart_rate,
    ),
    DataTypeSpec(
        "daily-heart-rate-variability", "dailyHeartRateVariability.date",
        DEFAULT_WINDOW_DAYS, METRICS_SCOPE, parse_daily_heart_rate_variability,
    ),
    DataTypeSpec(
        "daily-respiratory-rate", "dailyRespiratoryRate.date",
        DEFAULT_WINDOW_DAYS, METRICS_SCOPE, parse_daily_respiratory_rate,
    ),
    DataTypeSpec(
        "daily-oxygen-saturation", "dailyOxygenSaturation.date",
        DEFAULT_WINDOW_DAYS, METRICS_SCOPE, parse_daily_oxygen_saturation,
    ),
    DataTypeSpec(
        "daily-sleep-temperature-derivations", "dailySleepTemperatureDerivations.date",
        DEFAULT_WINDOW_DAYS, METRICS_SCOPE, parse_daily_sleep_temperature_derivations,
    ),
    DataTypeSpec(
        "steps", "steps.interval.civil_start_time",
        STEPS_WINDOW_DAYS, ACTIVITY_SCOPE, parse_steps,
    ),
    DataTypeSpec(
        "active-zone-minutes", "activeZoneMinutes.interval.civil_start_time",
        DEFAULT_WINDOW_DAYS, ACTIVITY_SCOPE, parse_active_zone_minutes,
    ),
    DataTypeSpec(
        "sleep", "sleep.session.end_time",
        DEFAULT_WINDOW_DAYS, SLEEP_SCOPE, parse_sleep, page_size=25,
    ),
    DataTypeSpec(
        "weight", "weight.sample_time.physical_time",
        DEFAULT_WINDOW_DAYS, METRICS_SCOPE, parse_weight,
    ),
    DataTypeSpec(
        "height", "height.sample_time.physical_time",
        DEFAULT_WINDOW_DAYS, METRICS_SCOPE, parse_height,
    ),
    # Polled so the coverage table can confirm what the Air does not produce.
    DataTypeSpec(
        "daily-vo2-max", "dailyVo2Max.date",
        DEFAULT_WINDOW_DAYS, ACTIVITY_SCOPE, _noop, expected_empty=True,
    ),
)

_BY_ID = {spec.data_type_id: spec for spec in DATA_TYPES}


def get_spec(data_type_id: str) -> DataTypeSpec:
    return _BY_ID[data_type_id]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/ingest/test_registry.py -v`
Expected: PASS — 13 passed

- [ ] **Step 5: Confirm filter field names against the live docs**

Open https://developers.google.com/health/data-types and, for each entry in `DATA_TYPES`,
confirm the documented filter field. Correct any mismatch in the registry and note the
date checked in a comment. Do not skip this: a wrong filter field returns HTTP 400, and
the failure surfaces only against the real API.

- [ ] **Step 6: Commit**

```bash
git add backend/src/bioage/ingest backend/tests/ingest
git commit -m "feat: data type registry isolating all Google-side constants"
```

---

### Task 20: Google Health HTTP client

**Files:**
- Create: `backend/src/bioage/ingest/client.py`
- Create: `backend/tests/ingest/test_client.py`

**Interfaces:**
- Consumes: `DataTypeSpec`, `DateRange`
- Produces:
  - `BASE_URL = "https://health.googleapis.com/v4"`
  - `GoogleHealthClient(token_provider: Callable[[], str], http: httpx.Client | None = None)`
  - `.build_filter(spec, window) -> str`
  - `.list_data_points(spec, window) -> list[dict]` — paginates, chunks by `max_window_days`, retries 429/5xx
  - `RateLimitedError`, `GoogleHealthError`

- [ ] **Step 1: Write the failing test**

`backend/tests/ingest/test_client.py`:
```python
from datetime import date

import httpx
import pytest
import respx

from bioage.ingest.client import BASE_URL, GoogleHealthClient, GoogleHealthError
from bioage.ingest.registry import get_spec
from bioage.types import DateRange


def make_client(**kwargs) -> GoogleHealthClient:
    return GoogleHealthClient(token_provider=lambda: "test-token", sleep=lambda _: None, **kwargs)


def test_filter_expression_uses_the_specs_filter_field():
    spec = get_spec("daily-resting-heart-rate")
    window = DateRange(date(2026, 6, 1), date(2026, 6, 15))
    built = make_client().build_filter(spec, window)
    assert "dailyRestingHeartRate.date" in built
    assert '"2026-06-01"' in built
    assert '"2026-06-15"' in built
    assert " AND " in built


@respx.mock
def test_sends_the_bearer_token():
    route = respx.get(url__startswith=f"{BASE_URL}/users/me/dataTypes/").mock(
        return_value=httpx.Response(200, json={"dataPoints": []})
    )
    make_client().list_data_points(
        get_spec("daily-resting-heart-rate"), DateRange(date(2026, 6, 1), date(2026, 6, 10))
    )
    assert route.calls[0].request.headers["Authorization"] == "Bearer test-token"


@respx.mock
def test_follows_pagination_until_the_token_is_exhausted():
    responses = [
        httpx.Response(200, json={"dataPoints": [{"a": 1}], "nextPageToken": "p2"}),
        httpx.Response(200, json={"dataPoints": [{"a": 2}], "nextPageToken": "p3"}),
        httpx.Response(200, json={"dataPoints": [{"a": 3}]}),
    ]
    respx.get(url__startswith=BASE_URL).mock(side_effect=responses)
    points = make_client().list_data_points(
        get_spec("daily-resting-heart-rate"), DateRange(date(2026, 6, 1), date(2026, 6, 10))
    )
    assert len(points) == 3


@respx.mock
def test_sixty_day_steps_backfill_is_split_into_five_requests():
    """The steps query cap is 14 days, so a 60-day range needs five sequential calls."""
    route = respx.get(url__startswith=BASE_URL).mock(
        return_value=httpx.Response(200, json={"dataPoints": []})
    )
    make_client().list_data_points(
        get_spec("steps"), DateRange(date(2026, 1, 1), date(2026, 3, 2))
    )
    assert route.call_count == 5


@respx.mock
def test_ninety_day_rhr_backfill_is_a_single_request():
    route = respx.get(url__startswith=BASE_URL).mock(
        return_value=httpx.Response(200, json={"dataPoints": []})
    )
    make_client().list_data_points(
        get_spec("daily-resting-heart-rate"), DateRange(date(2026, 1, 1), date(2026, 3, 31))
    )
    assert route.call_count == 1


@respx.mock
def test_retries_after_a_429_and_then_succeeds():
    respx.get(url__startswith=BASE_URL).mock(side_effect=[
        httpx.Response(429, json={"error": {"message": "rate limited"}}),
        httpx.Response(200, json={"dataPoints": [{"ok": True}]}),
    ])
    points = make_client().list_data_points(
        get_spec("daily-resting-heart-rate"), DateRange(date(2026, 6, 1), date(2026, 6, 10))
    )
    assert len(points) == 1


@respx.mock
def test_retries_a_500_then_succeeds():
    respx.get(url__startswith=BASE_URL).mock(side_effect=[
        httpx.Response(500),
        httpx.Response(200, json={"dataPoints": []}),
    ])
    assert make_client().list_data_points(
        get_spec("daily-resting-heart-rate"), DateRange(date(2026, 6, 1), date(2026, 6, 10))
    ) == []


@respx.mock
def test_gives_up_after_the_retry_budget():
    respx.get(url__startswith=BASE_URL).mock(return_value=httpx.Response(429))
    with pytest.raises(GoogleHealthError, match="429"):
        make_client(max_retries=2).list_data_points(
            get_spec("daily-resting-heart-rate"), DateRange(date(2026, 6, 1), date(2026, 6, 10))
        )


@respx.mock
def test_does_not_retry_a_403():
    """A missing scope is not transient; retrying wastes quota and hides the cause."""
    route = respx.get(url__startswith=BASE_URL).mock(
        return_value=httpx.Response(403, json={"error": {"message": "insufficient scope"}})
    )
    with pytest.raises(GoogleHealthError, match="403"):
        make_client().list_data_points(
            get_spec("daily-resting-heart-rate"), DateRange(date(2026, 6, 1), date(2026, 6, 10))
        )
    assert route.call_count == 1


@respx.mock
def test_requests_the_specs_page_size():
    route = respx.get(url__startswith=BASE_URL).mock(
        return_value=httpx.Response(200, json={"dataPoints": []})
    )
    make_client().list_data_points(
        get_spec("sleep"), DateRange(date(2026, 6, 1), date(2026, 6, 10))
    )
    assert route.calls[0].request.url.params["pageSize"] == "25"


@respx.mock
def test_url_targets_the_correct_host_and_path():
    route = respx.get(url__startswith=BASE_URL).mock(
        return_value=httpx.Response(200, json={"dataPoints": []})
    )
    make_client().list_data_points(
        get_spec("steps"), DateRange(date(2026, 6, 1), date(2026, 6, 10))
    )
    url = str(route.calls[0].request.url)
    assert url.startswith("https://health.googleapis.com/v4/users/me/dataTypes/steps/dataPoints")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/ingest/test_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bioage.ingest.client'`

- [ ] **Step 3: Implement the client**

`backend/src/bioage/ingest/client.py`:
```python
"""HTTP client for the Google Health API.

Responsibilities kept deliberately narrow: build a filter expression, chunk a date range
to the data type's documented cap, paginate, retry what is transient, and return raw
payloads. Parsing happens elsewhere.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from bioage.ingest.registry import DataTypeSpec
from bioage.types import DateRange

BASE_URL = "https://health.googleapis.com/v4"

RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
DEFAULT_MAX_RETRIES = 5
DEFAULT_BACKOFF_SECONDS = 1.0


class GoogleHealthError(RuntimeError):
    """A request failed and is not worth retrying, or the retry budget was exhausted."""


class GoogleHealthClient:
    def __init__(
        self,
        token_provider: Callable[[], str],
        http: httpx.Client | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._token_provider = token_provider
        self._http = http or httpx.Client(timeout=30.0)
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep

    def build_filter(self, spec: DataTypeSpec, window: DateRange) -> str:
        """AIP-160 filter constraining the query to a half-open date interval."""
        field = spec.filter_field
        return f'{field} >= "{window.start.isoformat()}" AND {field} < "{window.end.isoformat()}"'

    def list_data_points(self, spec: DataTypeSpec, window: DateRange) -> list[dict]:
        """Fetch every data point in `window`, chunking and paginating as needed."""
        points: list[dict] = []
        for chunk in window.chunked(spec.max_window_days):
            points.extend(self._list_chunk(spec, chunk))
        return points

    def _list_chunk(self, spec: DataTypeSpec, window: DateRange) -> list[dict]:
        url = f"{BASE_URL}/users/me/dataTypes/{spec.data_type_id}/dataPoints"
        params: dict[str, str | int] = {
            "filter": self.build_filter(spec, window),
            "pageSize": spec.page_size,
        }
        collected: list[dict] = []

        while True:
            payload = self._get(url, params)
            collected.extend(payload.get("dataPoints") or [])
            token = payload.get("nextPageToken")
            if not token:
                return collected
            params = {**params, "pageToken": token}

    def _get(self, url: str, params: dict) -> dict:
        last_status: int | None = None

        for attempt in range(self._max_retries):
            response = self._http.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {self._token_provider()}"},
            )
            if response.status_code == 200:
                return response.json()

            last_status = response.status_code
            if response.status_code not in RETRYABLE_STATUSES:
                raise GoogleHealthError(
                    f"Google Health API returned {response.status_code}: {response.text[:300]}"
                )
            # Exponential backoff; Retry-After wins when the server supplies it.
            delay = self._backoff_seconds * (2**attempt)
            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                delay = float(retry_after)
            self._sleep(delay)

        raise GoogleHealthError(
            f"Google Health API returned {last_status} after {self._max_retries} attempts"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/ingest/test_client.py -v`
Expected: PASS — 11 passed

- [ ] **Step 5: Commit**

```bash
git add backend/src/bioage/ingest/client.py backend/tests/ingest/test_client.py
git commit -m "feat: Google Health client with pagination, window chunking and retry"
```

---

### Task 21: OAuth flow and credential storage

**Files:**
- Create: `backend/src/bioage/ingest/oauth.py`
- Create: `backend/tests/ingest/test_oauth.py`

**Interfaces:**
- Consumes: `Settings`, `OAuthCredential`, `SCOPES`
- Produces:
  - `build_authorization_url(settings, state: str) -> str`
  - `exchange_code(settings, code: str, http) -> dict` — returns Google's token response
  - `store_credentials(session, token_response: dict) -> OAuthCredential`
  - `access_token(session, settings, http, now) -> str` — returns a valid token, refreshing when expired
  - `NotConnectedError`

- [ ] **Step 1: Write the failing test**

`backend/tests/ingest/test_oauth.py`:
```python
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from bioage.config import Settings
from bioage.db.models import OAuthCredential
from bioage.ingest.oauth import (
    NotConnectedError,
    access_token,
    build_authorization_url,
    exchange_code,
    store_credentials,
)

TOKEN_URL = "https://oauth2.googleapis.com/token"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="postgresql+psycopg://u:p@db:5432/x",
        google_client_id="client-123",
        google_client_secret="secret-456",
        oauth_redirect_uri="http://localhost:8000/api/auth/google/callback",
    )


def test_authorization_url_requests_all_three_scopes(settings):
    query = parse_qs(urlparse(build_authorization_url(settings, state="abc")).query)
    assert len(query["scope"][0].split()) == 3
    assert "googlehealth.sleep.readonly" in query["scope"][0]


def test_authorization_url_forces_a_refresh_token(settings):
    """Without access_type=offline and prompt=consent, Google may omit the refresh token."""
    query = parse_qs(urlparse(build_authorization_url(settings, state="abc")).query)
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["response_type"] == ["code"]


def test_authorization_url_carries_client_id_redirect_and_state(settings):
    query = parse_qs(urlparse(build_authorization_url(settings, state="xyz")).query)
    assert query["client_id"] == ["client-123"]
    assert query["state"] == ["xyz"]
    assert query["redirect_uri"] == ["http://localhost:8000/api/auth/google/callback"]


@respx.mock
def test_exchange_code_posts_the_authorization_code(settings):
    route = respx.post(TOKEN_URL).mock(return_value=httpx.Response(
        200, json={"access_token": "at", "refresh_token": "rt", "expires_in": 3599}
    ))
    result = exchange_code(settings, code="the-code", http=httpx.Client())
    assert result["refresh_token"] == "rt"
    body = dict(parse_qs(route.calls[0].request.content.decode()))
    assert body["code"] == ["the-code"]
    assert body["grant_type"] == ["authorization_code"]


@respx.mock
def test_exchange_code_raises_on_failure(settings):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "bad_verifier"}))
    with pytest.raises(RuntimeError, match="bad_verifier"):
        exchange_code(settings, code="nope", http=httpx.Client())


def test_store_credentials_persists_a_singleton(db):
    for token in ("rt-1", "rt-2"):
        store_credentials(db, {
            "access_token": "at", "refresh_token": token, "expires_in": 3600,
            "scope": "a b",
        })
    db.flush()
    assert db.query(OAuthCredential).count() == 1
    assert db.get(OAuthCredential, 1).refresh_token == "rt-2"


def test_store_credentials_keeps_the_existing_refresh_token_when_google_omits_it(db):
    """Google returns refresh_token only on first consent; a refresh response lacks it."""
    store_credentials(db, {"access_token": "at1", "refresh_token": "rt", "expires_in": 3600})
    store_credentials(db, {"access_token": "at2", "expires_in": 3600})
    db.flush()
    assert db.get(OAuthCredential, 1).refresh_token == "rt"
    assert db.get(OAuthCredential, 1).access_token == "at2"


def test_access_token_raises_when_not_connected(db, settings):
    with pytest.raises(NotConnectedError):
        access_token(db, settings, http=httpx.Client())


def test_access_token_returns_the_stored_token_while_valid(db, settings):
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    db.add(OAuthCredential(id=1, refresh_token="rt", access_token="still-good",
                           token_expiry=future, scopes=[]))
    db.flush()
    assert access_token(db, settings, http=httpx.Client()) == "still-good"


@respx.mock
def test_access_token_refreshes_when_expired(db, settings):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(
        200, json={"access_token": "fresh", "expires_in": 3599}
    ))
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.add(OAuthCredential(id=1, refresh_token="rt", access_token="stale",
                           token_expiry=past, scopes=[]))
    db.flush()
    assert access_token(db, settings, http=httpx.Client()) == "fresh"


@respx.mock
def test_refresh_uses_the_refresh_token_grant(db, settings):
    route = respx.post(TOKEN_URL).mock(return_value=httpx.Response(
        200, json={"access_token": "fresh", "expires_in": 3599}
    ))
    db.add(OAuthCredential(id=1, refresh_token="rt-value", access_token=None,
                           token_expiry=None, scopes=[]))
    db.flush()
    access_token(db, settings, http=httpx.Client())
    body = dict(parse_qs(route.calls[0].request.content.decode()))
    assert body["grant_type"] == ["refresh_token"]
    assert body["refresh_token"] == ["rt-value"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/ingest/test_oauth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bioage.ingest.oauth'`

- [ ] **Step 3: Implement OAuth**

`backend/src/bioage/ingest/oauth.py`:
```python
"""Google OAuth 2.0 authorization-code flow.

The web flow is used rather than google-auth's InstalledAppFlow.run_local_server, which
opens a browser and binds a port on the machine running the code — neither of which works
from inside a container.

Google returns a refresh token only on the first consent, and only when access_type is
offline with prompt=consent. Refresh responses omit it, so stored refresh tokens are
never overwritten with None.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from bioage.config import Settings
from bioage.db.models import OAuthCredential
from bioage.ingest.registry import SCOPES

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"

# Refresh slightly early so a token cannot expire mid-sync.
EXPIRY_MARGIN = timedelta(seconds=120)


class NotConnectedError(RuntimeError):
    """No Google credentials are stored; the user has not completed the OAuth flow."""


def build_authorization_url(settings: Settings, state: str) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.oauth_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "include_granted_scopes": "true",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _post_token(http: httpx.Client, data: dict[str, str]) -> dict:
    response = http.post(TOKEN_URL, data=data)
    if response.status_code != 200:
        raise RuntimeError(f"Google token endpoint returned {response.status_code}: {response.text}")
    return response.json()


def exchange_code(settings: Settings, code: str, http: httpx.Client) -> dict:
    return _post_token(http, {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": settings.oauth_redirect_uri,
        "grant_type": "authorization_code",
    })


def store_credentials(session: Session, token_response: dict) -> OAuthCredential:
    credential = session.get(OAuthCredential, 1) or OAuthCredential(id=1, refresh_token="")

    refresh_token = token_response.get("refresh_token")
    if refresh_token:
        credential.refresh_token = refresh_token
    elif not credential.refresh_token:
        raise RuntimeError(
            "Google did not return a refresh token. Revoke the app's access in your Google "
            "Account and reconnect so consent is prompted again."
        )

    credential.access_token = token_response.get("access_token")
    expires_in = token_response.get("expires_in")
    credential.token_expiry = (
        datetime.now(timezone.utc) + timedelta(seconds=int(expires_in)) if expires_in else None
    )
    scope = token_response.get("scope")
    if scope:
        credential.scopes = scope.split()
    return session.merge(credential)


def access_token(
    session: Session,
    settings: Settings,
    http: httpx.Client,
    now: datetime | None = None,
) -> str:
    """Return a currently valid access token, refreshing it if necessary."""
    credential = session.get(OAuthCredential, 1)
    if credential is None:
        raise NotConnectedError("No Google credentials stored. Complete the OAuth flow first.")

    moment = now or datetime.now(timezone.utc)
    if (
        credential.access_token
        and credential.token_expiry
        and credential.token_expiry - EXPIRY_MARGIN > moment
    ):
        return credential.access_token

    refreshed = _post_token(http, {
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "refresh_token": credential.refresh_token,
        "grant_type": "refresh_token",
    })
    stored = store_credentials(session, refreshed)
    session.flush()
    if not stored.access_token:
        raise RuntimeError("Token refresh succeeded but returned no access token")
    return stored.access_token
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/ingest/test_oauth.py -v`
Expected: PASS — 12 passed

- [ ] **Step 5: Commit**

```bash
git add backend/src/bioage/ingest/oauth.py backend/tests/ingest/test_oauth.py
git commit -m "feat: Google OAuth authorization-code flow with durable refresh tokens"
```

---

### Task 22: Sync service, watermarks and scheduler

**Files:**
- Create: `backend/src/bioage/ingest/sync.py`
- Create: `backend/src/bioage/ingest/scheduler.py`
- Modify: `backend/src/bioage/cli.py` (add the `sync` command)
- Create: `backend/tests/ingest/test_sync.py`

**Interfaces:**
- Consumes: `GoogleHealthClient`, `DATA_TYPES`, `RawDataPoint`, `DailyMetric`, `SyncState`, `rescore_all`
- Produces:
  - `SyncReport` — frozen dataclass: `data_type: str`, `points_fetched: int`, `days_written: int`, `error: str | None`
  - `SyncService(session, client, backfill_days)` with `.sync_all(today) -> list[SyncReport]`, `.sync_data_type(spec, today) -> SyncReport`
  - `normalize_all(session) -> int` — re-parse every raw point into `daily_metrics`
  - `scheduler.start_scheduler(settings) -> BackgroundScheduler | None`

- [ ] **Step 1: Write the failing test**

`backend/tests/ingest/test_sync.py`:
```python
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from bioage.db.models import DailyMetric, RawDataPoint, SyncState
from bioage.ingest.registry import get_spec
from bioage.ingest.sync import SyncService, normalize_all

FIXTURES = Path(__file__).parent.parent / "fixtures" / "googlehealth"


class FakeClient:
    """Returns the fixture payload for each data type and records the windows requested."""

    def __init__(self, payloads: dict[str, list[dict]] | None = None):
        self.payloads = payloads or {}
        self.requested: list[tuple[str, date, date]] = []

    def list_data_points(self, spec, window):
        self.requested.append((spec.data_type_id, window.start, window.end))
        return self.payloads.get(spec.data_type_id, [])


def fixture_points(name: str) -> list[dict]:
    return json.loads((FIXTURES / f"{name}.json").read_text())["dataPoints"]


@pytest.fixture
def client() -> FakeClient:
    return FakeClient({
        "daily-resting-heart-rate": fixture_points("daily_resting_heart_rate"),
        "daily-heart-rate-variability": fixture_points("daily_heart_rate_variability"),
        "steps": fixture_points("steps"),
        "sleep": fixture_points("sleep"),
    })


def test_sync_stores_raw_payloads_before_parsing(db, client):
    SyncService(db, client, backfill_days=30).sync_data_type(
        get_spec("daily-resting-heart-rate"), today=date(2026, 6, 10)
    )
    db.flush()
    assert db.query(RawDataPoint).count() == 2


def test_sync_writes_normalized_daily_metrics(db, client):
    SyncService(db, client, backfill_days=30).sync_data_type(
        get_spec("daily-resting-heart-rate"), today=date(2026, 6, 10)
    )
    db.flush()
    metric = db.get(DailyMetric, date(2026, 6, 1))
    assert metric is not None
    assert metric.resting_hr_bpm == pytest.approx(58.0)


def test_sync_merges_data_types_into_one_daily_row(db, client):
    service = SyncService(db, client, backfill_days=30)
    service.sync_data_type(get_spec("daily-resting-heart-rate"), today=date(2026, 6, 10))
    service.sync_data_type(get_spec("daily-heart-rate-variability"), today=date(2026, 6, 10))
    db.flush()
    metric = db.get(DailyMetric, date(2026, 6, 1))
    assert metric.resting_hr_bpm == pytest.approx(58.0)
    assert metric.hrv_rmssd_ms == pytest.approx(46.7)


def test_first_sync_backfills_the_configured_window(db, client):
    SyncService(db, client, backfill_days=45).sync_data_type(
        get_spec("daily-resting-heart-rate"), today=date(2026, 6, 10)
    )
    requested_start = client.requested[0][1]
    assert requested_start == date(2026, 6, 10) - timedelta(days=45)


def test_subsequent_sync_resumes_from_the_watermark(db, client):
    db.add(SyncState(data_type="daily-resting-heart-rate", synced_through=date(2026, 6, 5)))
    db.flush()
    SyncService(db, client, backfill_days=90).sync_data_type(
        get_spec("daily-resting-heart-rate"), today=date(2026, 6, 10)
    )
    assert client.requested[0][1] == date(2026, 6, 5)


def test_watermark_advances_after_a_successful_sync(db, client):
    SyncService(db, client, backfill_days=30).sync_data_type(
        get_spec("daily-resting-heart-rate"), today=date(2026, 6, 10)
    )
    db.flush()
    assert db.get(SyncState, "daily-resting-heart-rate").synced_through == date(2026, 6, 10)


def test_watermark_does_not_advance_when_the_fetch_fails(db):
    class Failing:
        def list_data_points(self, spec, window):
            raise RuntimeError("boom")

    report = SyncService(db, Failing(), backfill_days=30).sync_data_type(
        get_spec("daily-resting-heart-rate"), today=date(2026, 6, 10)
    )
    db.flush()
    assert report.error is not None
    assert db.get(SyncState, "daily-resting-heart-rate").synced_through is None


def test_one_failing_data_type_does_not_abort_the_others(db, client):
    reports = SyncService(db, client, backfill_days=30).sync_all(today=date(2026, 6, 10))
    assert len(reports) > 1
    assert any(r.points_fetched > 0 for r in reports)


def test_resync_is_idempotent(db, client):
    service = SyncService(db, client, backfill_days=30)
    service.sync_data_type(get_spec("daily-resting-heart-rate"), today=date(2026, 6, 10))
    db.flush()
    first = db.query(RawDataPoint).count()
    db.query(SyncState).delete()
    service.sync_data_type(get_spec("daily-resting-heart-rate"), today=date(2026, 6, 10))
    db.flush()
    assert db.query(RawDataPoint).count() == first


def test_normalize_all_reparses_stored_raw_without_refetching(db, client):
    SyncService(db, client, backfill_days=30).sync_data_type(
        get_spec("daily-resting-heart-rate"), today=date(2026, 6, 10)
    )
    db.flush()
    db.query(DailyMetric).delete()
    db.flush()
    written = normalize_all(db)
    db.flush()
    assert written > 0
    assert db.get(DailyMetric, date(2026, 6, 1)).resting_hr_bpm == pytest.approx(58.0)


def test_expected_empty_types_report_zero_without_error(db):
    report = SyncService(db, FakeClient(), backfill_days=30).sync_data_type(
        get_spec("daily-vo2-max"), today=date(2026, 6, 10)
    )
    assert report.error is None
    assert report.points_fetched == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/ingest/test_sync.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bioage.ingest.sync'`

- [ ] **Step 3: Implement the sync service**

`backend/src/bioage/ingest/sync.py`:
```python
"""Sync orchestration: fetch, store raw, normalize, advance the watermark.

Raw payloads are written before parsing so a parser fix never requires re-fetching data
that may have aged out of the API's queryable window. Each data type advances its own
watermark independently, and a failure in one does not abort the others: a wearable that
never populated VO2max should not block resting heart rate from syncing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from bioage.db.models import DailyMetric, RawDataPoint, SyncState
from bioage.ingest.registry import DATA_TYPES, DataTypeSpec, get_spec
from bioage.types import DateRange

logger = logging.getLogger(__name__)


class DataPointSource(Protocol):
    def list_data_points(self, spec: DataTypeSpec, window: DateRange) -> list[dict]: ...


@dataclass(frozen=True)
class SyncReport:
    data_type: str
    points_fetched: int
    days_written: int
    error: str | None = None


def _upsert_daily(session: Session, day: date, values: dict[str, float]) -> None:
    """Merge parsed values into the day's row without clobbering other data types."""
    if not values:
        return
    statement = (
        insert(DailyMetric)
        .values(date=day, **values)
        .on_conflict_do_update(index_elements=[DailyMetric.date], set_=values)
    )
    session.execute(statement)


class SyncService:
    def __init__(self, session: Session, client: DataPointSource, backfill_days: int) -> None:
        self._session = session
        self._client = client
        self._backfill_days = backfill_days

    def _window(self, spec: DataTypeSpec, today: date) -> DateRange | None:
        state = self._session.get(SyncState, spec.data_type_id)
        start = (
            state.synced_through
            if state and state.synced_through
            else today - timedelta(days=self._backfill_days)
        )
        return DateRange(start, today) if start < today else None

    def sync_data_type(self, spec: DataTypeSpec, today: date) -> SyncReport:
        window = self._window(spec, today)
        if window is None:
            return SyncReport(spec.data_type_id, 0, 0, None)

        state = self._session.get(SyncState, spec.data_type_id) or SyncState(
            data_type=spec.data_type_id
        )
        state.last_run_at = datetime.now(timezone.utc)

        try:
            points = self._client.list_data_points(spec, window)
        except Exception as exc:  # noqa: BLE001 - one type's failure must not abort the rest
            logger.warning("sync failed for %s: %s", spec.data_type_id, exc)
            state.last_error = str(exc)[:500]
            self._session.merge(state)
            return SyncReport(spec.data_type_id, 0, 0, error=str(exc))

        days_written = 0
        for payload in points:
            parsed = spec.parser(payload)
            point_date = parsed.day if parsed else window.start
            self._session.execute(
                insert(RawDataPoint)
                .values(data_type=spec.data_type_id, point_date=point_date, payload=payload)
                .on_conflict_do_update(
                    index_elements=[RawDataPoint.data_type, RawDataPoint.point_date],
                    set_={"payload": payload},
                )
            )
            if parsed:
                _upsert_daily(self._session, parsed.day, parsed.values)
                days_written += 1

        state.synced_through = today
        state.last_error = None
        self._session.merge(state)
        return SyncReport(spec.data_type_id, len(points), days_written, None)

    def sync_all(self, today: date | None = None) -> list[SyncReport]:
        moment = today or date.today()
        return [self.sync_data_type(spec, moment) for spec in DATA_TYPES]


def normalize_all(session: Session) -> int:
    """Re-parse every stored raw payload into daily_metrics. No network access."""
    rows = session.execute(select(RawDataPoint)).scalars().all()
    written = 0
    for row in rows:
        try:
            spec = get_spec(row.data_type)
        except KeyError:
            continue
        parsed = spec.parser(row.payload)
        if parsed:
            _upsert_daily(session, parsed.day, parsed.values)
            written += 1
    return written
```

- [ ] **Step 4: Implement the scheduler**

`backend/src/bioage/ingest/scheduler.py`:
```python
"""Optional daily sync job.

Disabled by default: a freshly installed personal app should not make network calls the
user did not ask for.
"""

from __future__ import annotations

import logging

import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from bioage.config import Settings
from bioage.db.base import session_factory
from bioage.ingest.client import GoogleHealthClient
from bioage.ingest.oauth import access_token
from bioage.ingest.sync import SyncService
from bioage.scoring import rescore_all

logger = logging.getLogger(__name__)


def run_scheduled_sync(settings: Settings) -> None:
    with session_factory(settings.database_url)() as session, httpx.Client(timeout=30) as http:
        client = GoogleHealthClient(
            token_provider=lambda: access_token(session, settings, http)
        )
        reports = SyncService(session, client, settings.backfill_days).sync_all()
        rescore_all(session)
        session.commit()
    failed = [r.data_type for r in reports if r.error]
    logger.info("scheduled sync complete; %d data types failed: %s", len(failed), failed)


def start_scheduler(settings: Settings) -> BackgroundScheduler | None:
    if not settings.sync_schedule_enabled:
        return None
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_scheduled_sync,
        trigger=CronTrigger.from_crontab(settings.sync_schedule_cron),
        args=[settings],
        id="daily-sync",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("sync scheduler started with cron %s", settings.sync_schedule_cron)
    return scheduler
```

- [ ] **Step 5: Add the sync CLI command**

Append to `backend/src/bioage/cli.py`:
```python
@app.command("sync")
def sync_command() -> None:
    """Pull new data from the Google Health API and rescore."""
    import httpx

    from bioage.ingest.client import GoogleHealthClient
    from bioage.ingest.oauth import access_token
    from bioage.ingest.sync import SyncService

    settings = get_settings()
    with session_factory(settings.database_url)() as session, httpx.Client(timeout=30) as http:
        client = GoogleHealthClient(
            token_provider=lambda: access_token(session, settings, http)
        )
        reports = SyncService(session, client, settings.backfill_days).sync_all()
        weeks = rescore_all(session)
        session.commit()

    for report in reports:
        status = f"ERROR: {report.error}" if report.error else f"{report.days_written} days"
        typer.echo(f"  {report.data_type}: {status}")
    typer.echo(f"Rescored {weeks} weeks.")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/ingest/test_sync.py -v`
Expected: PASS — 11 passed

- [ ] **Step 7: Commit**

```bash
git add backend/src/bioage/ingest/sync.py backend/src/bioage/ingest/scheduler.py \
        backend/src/bioage/cli.py backend/tests/ingest/test_sync.py
git commit -m "feat: sync service with per-data-type watermarks and optional scheduler"
```

---

## Phase H — HTTP API

### Task 23: FastAPI application and routes

**Files:**
- Create: `backend/src/bioage/api/__init__.py`
- Create: `backend/src/bioage/api/schemas.py`
- Create: `backend/src/bioage/api/deps.py`
- Create: `backend/src/bioage/api/routes_bioage.py`
- Create: `backend/src/bioage/api/routes_profile.py`
- Create: `backend/src/bioage/api/routes_sync.py`
- Create: `backend/src/bioage/api/routes_auth.py`
- Create: `backend/src/bioage/api/app.py`
- Create: `backend/tests/api/__init__.py`
- Create: `backend/tests/api/test_routes.py`

**Interfaces:**
- Consumes: everything above
- Produces: `create_app() -> FastAPI` and the endpoints listed in the spec's §6 table. Response models:
  - `SeriesPoint`: `week_start`, `chronological_age`, `composite_age`, `ci_low`, `ci_high`, `is_low_confidence`, `components: list[ComponentOut]`
  - `ComponentOut`: `component`, `age_years`, `sigma_years`, `inputs`
  - `ProfileOut`: `sex`, `birthdate`, `measurements: list[MeasurementOut]`
  - `SyncStatusOut`: `connected: bool`, `data_types: list[CoverageOut]`

- [ ] **Step 1: Write the failing test**

`backend/tests/api/test_routes.py`:
```python
from datetime import date

import pytest
from fastapi.testclient import TestClient

from bioage.api.app import create_app
from bioage.api.deps import get_session
from bioage.demo.generator import seed_demo


@pytest.fixture
def client(db):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db
    return TestClient(app)


@pytest.fixture
def seeded_client(client, db):
    seed_demo(db, days=200)
    db.flush()
    return client


def test_health_endpoint_reports_ok(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_series_is_empty_before_any_data(client):
    response = client.get("/api/bioage/series")
    assert response.status_code == 200
    assert response.json() == []


def test_series_returns_one_point_per_week_in_ascending_order(seeded_client):
    points = seeded_client.get("/api/bioage/series").json()
    assert len(points) > 20
    weeks = [p["week_start"] for p in points]
    assert weeks == sorted(weeks)


def test_every_series_point_carries_a_confidence_band(seeded_client):
    for point in seeded_client.get("/api/bioage/series").json():
        assert point["ci_low"] < point["composite_age"] < point["ci_high"]
        assert "chronological_age" in point


def test_series_respects_the_date_filters(seeded_client):
    all_points = seeded_client.get("/api/bioage/series").json()
    cutoff = all_points[len(all_points) // 2]["week_start"]
    filtered = seeded_client.get(f"/api/bioage/series?from_date={cutoff}").json()
    assert all(p["week_start"] >= cutoff for p in filtered)
    assert len(filtered) < len(all_points)


def test_week_detail_includes_components_and_coverage(seeded_client):
    week = seeded_client.get("/api/bioage/series").json()[-1]["week_start"]
    detail = seeded_client.get(f"/api/bioage/weeks/{week}").json()
    assert {c["component"] for c in detail["components"]}
    assert "total_days" in detail["coverage"]


def test_week_detail_404s_for_an_unscored_week(seeded_client):
    assert seeded_client.get("/api/bioage/weeks/1999-01-04").status_code == 404


def test_profile_404s_when_unset(client):
    assert client.get("/api/profile").status_code == 404


def test_profile_can_be_created_and_read_back(client):
    response = client.put("/api/profile", json={"sex": "female", "birthdate": "1988-02-29"})
    assert response.status_code == 200
    body = client.get("/api/profile").json()
    assert body["sex"] == "female"
    assert body["birthdate"] == "1988-02-29"


def test_profile_rejects_an_invalid_sex(client):
    assert client.put(
        "/api/profile", json={"sex": "unknown", "birthdate": "1988-02-29"}
    ).status_code == 422


def test_profile_rejects_a_future_birthdate(client):
    assert client.put(
        "/api/profile", json={"sex": "male", "birthdate": "2099-01-01"}
    ).status_code == 422


def test_measurements_can_be_added_and_listed(client):
    client.put("/api/profile", json={"sex": "male", "birthdate": "1990-01-01"})
    created = client.post(
        "/api/profile/measurements",
        json={"kind": "waist_cm", "value": 88.0, "measured_on": "2026-06-01"},
    )
    assert created.status_code == 201
    measurements = client.get("/api/profile").json()["measurements"]
    assert measurements[0]["kind"] == "waist_cm"


def test_measurement_rejects_an_unknown_kind(client):
    assert client.post(
        "/api/profile/measurements",
        json={"kind": "shoe_size", "value": 44.0, "measured_on": "2026-06-01"},
    ).status_code == 422


def test_measurement_rejects_a_non_positive_value(client):
    assert client.post(
        "/api/profile/measurements",
        json={"kind": "waist_cm", "value": 0.0, "measured_on": "2026-06-01"},
    ).status_code == 422


def test_measurement_can_be_deleted(client):
    client.put("/api/profile", json={"sex": "male", "birthdate": "1990-01-01"})
    created = client.post(
        "/api/profile/measurements",
        json={"kind": "waist_cm", "value": 88.0, "measured_on": "2026-06-01"},
    ).json()
    assert client.delete(f"/api/profile/measurements/{created['id']}").status_code == 204
    assert client.get("/api/profile").json()["measurements"] == []


def test_sync_status_reports_disconnected_before_oauth(client):
    body = client.get("/api/sync/status").json()
    assert body["connected"] is False
    assert any(d["data_type"] == "steps" for d in body["data_types"])


def test_sync_status_lists_vo2max_as_expected_empty(client):
    body = client.get("/api/sync/status").json()
    vo2 = next(d for d in body["data_types"] if d["data_type"] == "daily-vo2-max")
    assert vo2["expected_empty"] is True


def test_sync_returns_409_when_not_connected(client):
    assert client.post("/api/sync").status_code == 409


def test_auth_start_returns_503_without_google_credentials(client):
    assert client.get("/api/auth/google/start", follow_redirects=False).status_code == 503


def test_daily_metrics_endpoint_returns_rows(seeded_client):
    rows = seeded_client.get("/api/daily-metrics").json()
    assert len(rows) > 0
    assert "date" in rows[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/api/test_routes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bioage.api.app'`

- [ ] **Step 3: Implement schemas and dependencies**

`backend/src/bioage/api/__init__.py`: empty file.

`backend/src/bioage/api/schemas.py`:
```python
"""Pydantic response and request models for the HTTP API."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bioage.db.models import MEASUREMENT_KINDS
from bioage.types import Sex


class ComponentOut(BaseModel):
    component: str
    age_years: float
    sigma_years: float
    inputs: dict[str, float]


class SeriesPoint(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    week_start: date
    chronological_age: float
    composite_age: float
    ci_low: float
    ci_high: float
    is_low_confidence: bool
    components: list[ComponentOut]


class WeekDetail(SeriesPoint):
    coverage: dict


class MeasurementIn(BaseModel):
    kind: str
    value: float = Field(gt=0)
    measured_on: date

    @field_validator("kind")
    @classmethod
    def known_kind(cls, value: str) -> str:
        if value not in MEASUREMENT_KINDS:
            raise ValueError(f"kind must be one of {MEASUREMENT_KINDS}")
        return value


class MeasurementOut(MeasurementIn):
    model_config = ConfigDict(from_attributes=True)

    id: int


class ProfileIn(BaseModel):
    sex: Sex
    birthdate: date

    @field_validator("birthdate")
    @classmethod
    def not_in_the_future(cls, value: date) -> date:
        if value >= date.today():
            raise ValueError("birthdate must be in the past")
        return value


class ProfileOut(BaseModel):
    sex: Sex
    birthdate: date
    measurements: list[MeasurementOut]


class DailyMetricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    resting_hr_bpm: float | None
    hrv_rmssd_ms: float | None
    steps: int | None
    sleep_efficiency_pct: float | None


class CoverageOut(BaseModel):
    data_type: str
    synced_through: date | None
    last_run_at: str | None
    last_error: str | None
    expected_empty: bool
    points_stored: int


class SyncStatusOut(BaseModel):
    connected: bool
    data_types: list[CoverageOut]
```

`backend/src/bioage/api/deps.py`:
```python
"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
from sqlalchemy.orm import Session

from bioage.config import Settings, get_settings
from bioage.db.base import session_factory


def get_session() -> Iterator[Session]:
    with session_factory(get_settings().database_url)() as session:
        yield session


def get_app_settings() -> Settings:
    return get_settings()


def get_http_client() -> Iterator[httpx.Client]:
    with httpx.Client(timeout=30.0) as client:
        yield client
```

- [ ] **Step 4: Implement the routers**

`backend/src/bioage/api/routes_bioage.py`:
```python
"""Biological age series and per-week detail."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from bioage.api.deps import get_session
from bioage.api.schemas import DailyMetricOut, SeriesPoint, WeekDetail
from bioage.db.models import BioAgeScore, DailyMetric

router = APIRouter(prefix="/api", tags=["bioage"])


@router.get("/bioage/series", response_model=list[SeriesPoint])
def get_series(
    from_date: date | None = None,
    to_date: date | None = None,
    session: Session = Depends(get_session),
) -> list[BioAgeScore]:
    stmt = select(BioAgeScore).order_by(BioAgeScore.week_start)
    if from_date:
        stmt = stmt.where(BioAgeScore.week_start >= from_date)
    if to_date:
        stmt = stmt.where(BioAgeScore.week_start <= to_date)
    return list(session.execute(stmt).scalars().all())


@router.get("/bioage/weeks/{week_start}", response_model=WeekDetail)
def get_week(week_start: date, session: Session = Depends(get_session)) -> BioAgeScore:
    score = session.get(BioAgeScore, week_start)
    if score is None:
        raise HTTPException(status_code=404, detail=f"No score for week starting {week_start}")
    return score


@router.get("/daily-metrics", response_model=list[DailyMetricOut])
def get_daily_metrics(
    from_date: date | None = None,
    to_date: date | None = None,
    session: Session = Depends(get_session),
) -> list[DailyMetric]:
    stmt = select(DailyMetric).order_by(DailyMetric.date)
    if from_date:
        stmt = stmt.where(DailyMetric.date >= from_date)
    if to_date:
        stmt = stmt.where(DailyMetric.date <= to_date)
    return list(session.execute(stmt).scalars().all())
```

`backend/src/bioage/api/routes_profile.py`:
```python
"""Profile and dated body measurements."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from bioage.api.deps import get_session
from bioage.api.schemas import MeasurementIn, MeasurementOut, ProfileIn, ProfileOut
from bioage.db.models import Measurement, Profile
from bioage.scoring import rescore_all

router = APIRouter(prefix="/api/profile", tags=["profile"])


def _measurements(session: Session) -> list[Measurement]:
    stmt = select(Measurement).order_by(Measurement.kind, Measurement.measured_on)
    return list(session.execute(stmt).scalars().all())


@router.get("", response_model=ProfileOut)
def get_profile(session: Session = Depends(get_session)) -> ProfileOut:
    profile = session.get(Profile, 1)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not set")
    return ProfileOut(
        sex=profile.sex,
        birthdate=profile.birthdate,
        measurements=[MeasurementOut.model_validate(m) for m in _measurements(session)],
    )


@router.put("", response_model=ProfileOut)
def put_profile(payload: ProfileIn, session: Session = Depends(get_session)) -> ProfileOut:
    session.merge(Profile(id=1, sex=payload.sex, birthdate=payload.birthdate))
    session.flush()
    rescore_all(session)
    session.commit()
    return get_profile(session)


@router.post("/measurements", response_model=MeasurementOut, status_code=201)
def add_measurement(
    payload: MeasurementIn, session: Session = Depends(get_session)
) -> Measurement:
    measurement = Measurement(**payload.model_dump())
    session.add(measurement)
    session.flush()
    rescore_all(session)
    session.commit()
    return measurement


@router.delete("/measurements/{measurement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_measurement(
    measurement_id: int, session: Session = Depends(get_session)
) -> Response:
    measurement = session.get(Measurement, measurement_id)
    if measurement is None:
        raise HTTPException(status_code=404, detail="Measurement not found")
    session.delete(measurement)
    session.flush()
    rescore_all(session)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

`backend/src/bioage/api/routes_sync.py`:
```python
"""Manual sync trigger and coverage reporting."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bioage.api.deps import get_app_settings, get_http_client, get_session
from bioage.api.schemas import CoverageOut, SyncStatusOut
from bioage.config import Settings
from bioage.db.models import OAuthCredential, RawDataPoint, SyncState
from bioage.ingest.client import GoogleHealthClient
from bioage.ingest.oauth import access_token
from bioage.ingest.registry import DATA_TYPES
from bioage.ingest.sync import SyncService
from bioage.scoring import rescore_all

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/status", response_model=SyncStatusOut)
def get_status(session: Session = Depends(get_session)) -> SyncStatusOut:
    states = {s.data_type: s for s in session.execute(select(SyncState)).scalars().all()}
    counts = dict(
        session.execute(
            select(RawDataPoint.data_type, func.count()).group_by(RawDataPoint.data_type)
        ).all()
    )
    return SyncStatusOut(
        connected=session.get(OAuthCredential, 1) is not None,
        data_types=[
            CoverageOut(
                data_type=spec.data_type_id,
                synced_through=states[spec.data_type_id].synced_through
                if spec.data_type_id in states else None,
                last_run_at=states[spec.data_type_id].last_run_at.isoformat()
                if spec.data_type_id in states and states[spec.data_type_id].last_run_at else None,
                last_error=states[spec.data_type_id].last_error
                if spec.data_type_id in states else None,
                expected_empty=spec.expected_empty,
                points_stored=counts.get(spec.data_type_id, 0),
            )
            for spec in DATA_TYPES
        ],
    )


@router.post("")
def trigger_sync(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
    http: httpx.Client = Depends(get_http_client),
) -> dict:
    if session.get(OAuthCredential, 1) is None:
        raise HTTPException(status_code=409, detail="Not connected to Google Health")

    client = GoogleHealthClient(token_provider=lambda: access_token(session, settings, http))
    reports = SyncService(session, client, settings.backfill_days).sync_all()
    weeks = rescore_all(session)
    session.commit()
    return {
        "weeks_scored": weeks,
        "reports": [
            {"data_type": r.data_type, "days_written": r.days_written, "error": r.error}
            for r in reports
        ],
    }
```

`backend/src/bioage/api/routes_auth.py`:
```python
"""Google OAuth endpoints."""

from __future__ import annotations

import secrets

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from bioage.api.deps import get_app_settings, get_http_client, get_session
from bioage.config import Settings
from bioage.db.models import OAuthCredential
from bioage.ingest.oauth import build_authorization_url, exchange_code, store_credentials

router = APIRouter(prefix="/api/auth/google", tags=["auth"])


@router.get("/start")
def start(settings: Settings = Depends(get_app_settings)) -> RedirectResponse:
    if not settings.is_google_configured:
        raise HTTPException(
            status_code=503,
            detail="GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are not set. See docs/SETUP.md.",
        )
    url = build_authorization_url(settings, state=secrets.token_urlsafe(16))
    return RedirectResponse(url)


@router.get("/callback")
def callback(
    code: str | None = None,
    error: str | None = None,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
    http: httpx.Client = Depends(get_http_client),
) -> RedirectResponse:
    if error:
        raise HTTPException(status_code=400, detail=f"Google returned an error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    store_credentials(session, exchange_code(settings, code, http))
    session.commit()
    return RedirectResponse(f"{settings.frontend_origin}/connection?connected=1")


@router.get("/status")
def status(session: Session = Depends(get_session)) -> dict:
    credential = session.get(OAuthCredential, 1)
    return {
        "connected": credential is not None,
        "connected_at": credential.connected_at.isoformat() if credential else None,
        "scopes": credential.scopes if credential else [],
    }
```

`backend/src/bioage/api/app.py`:
```python
"""FastAPI application factory."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bioage.api import routes_auth, routes_bioage, routes_profile, routes_sync
from bioage.config import get_settings
from bioage.ingest.scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Fitbit Air Biological Age", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(routes_bioage.router)
    app.include_router(routes_profile.router)
    app.include_router(routes_sync.router)
    app.include_router(routes_auth.router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    start_scheduler(settings)
    return app
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/api/test_routes.py -v`
Expected: PASS — 20 passed

- [ ] **Step 6: Run the full backend suite and linters**

Run:
```bash
cd backend
uv run pytest -v
uv run ruff check src tests
uv run mypy src/bioage/estimators src/bioage/biomarkers
```
Expected: all tests pass, no lint errors, no type errors.

- [ ] **Step 7: Verify the API serves the demo data**

Run:
```bash
docker compose up -d --build
sleep 10
curl -s localhost:8000/api/health
docker compose exec backend uv run python -m bioage.cli seed-demo --days 400
curl -s "localhost:8000/api/bioage/series" | head -c 400
```
Expected: `{"status":"ok"}` then a JSON array of weekly points each with `composite_age`, `ci_low`, `ci_high`.

- [ ] **Step 8: Commit**

```bash
git add backend/src/bioage/api backend/tests/api
git commit -m "feat: FastAPI routes for series, profile, sync and OAuth"
```

---

### Task 24: End-to-end integration test

**Files:**
- Create: `backend/tests/integration/__init__.py`
- Create: `backend/tests/integration/test_end_to_end.py`

**Interfaces:**
- Consumes: everything
- Produces: no new production code — this task proves the assembled pipeline works.

- [ ] **Step 1: Write the test**

`backend/tests/integration/test_end_to_end.py`:
```python
"""Sync -> normalize -> score -> serve, against a mocked Google Health API."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bioage.api.app import create_app
from bioage.api.deps import get_session
from bioage.db.models import BioAgeScore, DailyMetric, Measurement, Profile, RawDataPoint
from bioage.ingest.sync import SyncService, normalize_all
from bioage.types import Sex

FIXTURES = Path(__file__).parent.parent / "fixtures" / "googlehealth"


class ScriptedApi:
    """Serves a synthetic 120-day history in the documented payload shapes."""

    def __init__(self, end: date, days: int = 120):
        self.end = end
        self.days = days

    def list_data_points(self, spec, window):
        builders = {
            "daily-resting-heart-rate": self._rhr,
            "daily-heart-rate-variability": self._hrv,
            "steps": self._steps,
            "sleep": self._sleep,
        }
        builder = builders.get(spec.data_type_id)
        if builder is None:
            return []
        return [
            builder(self.end - timedelta(days=i))
            for i in range(self.days)
            if window.start <= self.end - timedelta(days=i) < window.end
        ]

    @staticmethod
    def _proto_date(day: date) -> dict:
        return {"year": day.year, "month": day.month, "day": day.day}

    def _rhr(self, day: date) -> dict:
        return {"dailyRestingHeartRate": {
            "date": self._proto_date(day), "beatsPerMinute": str(58 + day.day % 5)
        }}

    def _hrv(self, day: date) -> dict:
        return {"dailyHeartRateVariability": {
            "date": self._proto_date(day),
            "averageHeartRateVariabilityMilliseconds": 42.0,
            "deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds": 44.0 + day.day % 7,
        }}

    def _steps(self, day: date) -> dict:
        return {"steps": {
            "interval": {
                "startTime": f"{day.isoformat()}T00:00:00Z",
                "endTime": f"{(day + timedelta(days=1)).isoformat()}T00:00:00Z",
            },
            "count": str(8000 + day.day * 100),
        }}

    def _sleep(self, day: date) -> dict:
        previous = day - timedelta(days=1)
        return {"sleep": {
            "session": {
                "startTime": f"{previous.isoformat()}T23:00:00Z",
                "endTime": f"{day.isoformat()}T07:00:00Z",
            },
            "sleepMetadata": {"stagesState": "STAGES_AVAILABLE"},
            "sleepSummary": {
                "totalDuration": "28800s",
                "stageSummary": [
                    {"stage": "AWAKE", "duration": "2400s"},
                    {"stage": "LIGHT", "duration": "14400s"},
                    {"stage": "DEEP", "duration": "5400s"},
                    {"stage": "REM", "duration": "6600s"},
                ],
            },
            "sleepStages": [
                {"startTime": f"{previous.isoformat()}T23:10:00Z",
                 "endTime": f"{day.isoformat()}T01:10:00Z", "stage": "LIGHT"},
                {"startTime": f"{day.isoformat()}T01:10:00Z",
                 "endTime": f"{day.isoformat()}T01:30:00Z", "stage": "AWAKE"},
                {"startTime": f"{day.isoformat()}T01:30:00Z",
                 "endTime": f"{day.isoformat()}T07:00:00Z", "stage": "REM"},
            ],
        }}


@pytest.fixture
def profiled(db):
    db.add(Profile(id=1, sex=Sex.MALE, birthdate=date(1990, 3, 14)))
    db.add_all([
        Measurement(kind="height_m", value=1.78, measured_on=date(2026, 1, 1)),
        Measurement(kind="weight_kg", value=74.5, measured_on=date(2026, 1, 1)),
        Measurement(kind="waist_cm", value=87.0, measured_on=date(2026, 1, 1)),
    ])
    db.flush()
    return db


def test_full_pipeline_from_api_payloads_to_served_series(profiled):
    today = date(2026, 7, 1)
    service = SyncService(profiled, ScriptedApi(end=today), backfill_days=120)
    reports = service.sync_all(today=today)
    profiled.flush()

    assert not [r for r in reports if r.error]
    assert profiled.query(RawDataPoint).count() > 300
    assert profiled.query(DailyMetric).count() > 100

    from bioage.scoring import rescore_all
    weeks = rescore_all(profiled)
    profiled.flush()
    assert weeks > 10

    app = create_app()
    app.dependency_overrides[get_session] = lambda: profiled
    points = TestClient(app).get("/api/bioage/series").json()
    assert len(points) == weeks
    for point in points:
        assert point["ci_low"] < point["composite_age"] < point["ci_high"]
        assert 18.0 <= point["composite_age"] <= 100.0


def test_sleep_derivations_survive_the_whole_pipeline(profiled):
    today = date(2026, 7, 1)
    SyncService(profiled, ScriptedApi(end=today), backfill_days=60).sync_all(today=today)
    profiled.flush()
    metric = profiled.query(DailyMetric).filter(
        DailyMetric.sleep_efficiency_pct.isnot(None)
    ).first()
    assert metric is not None
    # LIGHT+DEEP+REM = 26400s of 480 minutes in bed
    assert metric.sleep_efficiency_pct == pytest.approx(440 / 480 * 100, abs=0.1)
    assert metric.waso_min == pytest.approx(20.0, abs=0.1)


def test_reparsing_raw_data_reproduces_identical_daily_metrics(profiled):
    today = date(2026, 7, 1)
    SyncService(profiled, ScriptedApi(end=today), backfill_days=60).sync_all(today=today)
    profiled.flush()
    before = {
        m.date: (m.resting_hr_bpm, m.hrv_rmssd_ms, m.steps)
        for m in profiled.query(DailyMetric).all()
    }
    profiled.query(DailyMetric).delete()
    profiled.flush()
    normalize_all(profiled)
    profiled.flush()
    after = {
        m.date: (m.resting_hr_bpm, m.hrv_rmssd_ms, m.steps)
        for m in profiled.query(DailyMetric).all()
    }
    assert after == before


def test_running_the_whole_pipeline_twice_changes_nothing(profiled):
    today = date(2026, 7, 1)
    from bioage.scoring import rescore_all

    api = ScriptedApi(end=today)
    SyncService(profiled, api, backfill_days=120).sync_all(today=today)
    rescore_all(profiled)
    profiled.flush()
    first = {s.week_start: s.composite_age for s in profiled.query(BioAgeScore).all()}

    SyncService(profiled, api, backfill_days=120).sync_all(today=today)
    rescore_all(profiled)
    profiled.flush()
    second = {s.week_start: s.composite_age for s in profiled.query(BioAgeScore).all()}

    assert first.keys() == second.keys()
    for week in first:
        assert first[week] == pytest.approx(second[week])


def test_changing_the_waist_measurement_only_affects_later_weeks(profiled):
    today = date(2026, 7, 1)
    from bioage.scoring import rescore_all

    SyncService(profiled, ScriptedApi(end=today), backfill_days=120).sync_all(today=today)
    rescore_all(profiled)
    profiled.flush()
    before = {s.week_start: s.composite_age for s in profiled.query(BioAgeScore).all()}

    profiled.add(Measurement(kind="waist_cm", value=79.0, measured_on=date(2026, 6, 1)))
    profiled.flush()
    rescore_all(profiled)
    profiled.flush()
    after = {s.week_start: s.composite_age for s in profiled.query(BioAgeScore).all()}

    early = [w for w in before if w < date(2026, 5, 1)]
    late = [w for w in before if w > date(2026, 6, 8)]
    assert early and late
    for week in early:
        assert after[week] == pytest.approx(before[week]), "past weeks must not be rewritten"
    assert any(after[w] != pytest.approx(before[w]) for w in late)
```

- [ ] **Step 2: Run the integration tests**

Run: `cd backend && uv run pytest tests/integration -v`
Expected: PASS — 5 passed

- [ ] **Step 3: Run the entire suite**

Run: `cd backend && uv run pytest -v`
Expected: PASS — every test green

- [ ] **Step 4: Commit**

```bash
git add backend/tests/integration
git commit -m "test: end-to-end pipeline from mocked API payloads to served series"
```

---

## Phase I — Frontend

### Task 25: Frontend scaffold, API client and series transform

**Files:**
- Create: `frontend/package.json`, `frontend/tsconfig.json`, `frontend/vite.config.ts`, `frontend/index.html`
- Create: `frontend/src/api/types.ts`, `frontend/src/api/client.ts`
- Create: `frontend/src/lib/series.ts`
- Create: `frontend/tests/series.test.ts`

**Interfaces:**
- Consumes: the backend API
- Produces:
  - `types.ts`: `SeriesPoint`, `Component`, `WeekDetail`, `Profile`, `Measurement`, `SyncStatus`, `CoverageRow`
  - `client.ts`: `getSeries`, `getWeek`, `getProfile`, `putProfile`, `addMeasurement`, `deleteMeasurement`, `getSyncStatus`, `triggerSync`, `getAuthStatus`
  - `series.ts`: `toChartRows(points: SeriesPoint[]): ChartRow[]` where `ChartRow` has `week`, `bioAge`, `chronoAge`, `ciLow`, `ciHigh`, `band: [number, number]`, `lowConfidence`, and `componentAges: Record<string, number>`; plus `componentKeys(points)` and `formatYears(value)`

- [ ] **Step 1: Scaffold the project**

`frontend/package.json`:
```json
{
  "name": "fitbit-air-bioage-frontend",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "lint": "tsc --noEmit"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.28.0",
    "recharts": "^2.13.3"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.6.3",
    "@testing-library/react": "^16.0.1",
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.4",
    "jsdom": "^25.0.1",
    "typescript": "^5.6.3",
    "vite": "^5.4.11",
    "vitest": "^2.1.5"
  }
}
```

`frontend/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "skipLibCheck": true,
    "isolatedModules": true,
    "noEmit": true,
    "types": ["vitest/globals"]
  },
  "include": ["src", "tests"]
}
```

`frontend/vite.config.ts`:
```typescript
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  test: { environment: "jsdom", globals: true },
});
```

`frontend/index.html`:
```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Biological Age</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 2: Write the failing test**

`frontend/tests/series.test.ts`:
```typescript
import { describe, expect, it } from "vitest";

import type { SeriesPoint } from "../src/api/types";
import { componentKeys, formatYears, toChartRows } from "../src/lib/series";

const point = (overrides: Partial<SeriesPoint> = {}): SeriesPoint => ({
  week_start: "2026-06-01",
  chronological_age: 36.2,
  composite_age: 33.8,
  ci_low: 28.1,
  ci_high: 39.5,
  is_low_confidence: false,
  components: [
    { component: "kdm", age_years: 34.0, sigma_years: 6.5, inputs: {} },
    { component: "hrv_norm", age_years: 32.0, sigma_years: 7.0, inputs: {} },
  ],
  ...overrides,
});

describe("toChartRows", () => {
  it("returns an empty array for no points", () => {
    expect(toChartRows([])).toEqual([]);
  });

  it("maps the composite and chronological ages", () => {
    const [row] = toChartRows([point()]);
    expect(row.bioAge).toBeCloseTo(33.8);
    expect(row.chronoAge).toBeCloseTo(36.2);
    expect(row.week).toBe("2026-06-01");
  });

  it("expresses the band as [low, high] for an area chart", () => {
    const [row] = toChartRows([point()]);
    expect(row.band).toEqual([28.1, 39.5]);
  });

  it("carries the low-confidence flag through", () => {
    const [row] = toChartRows([point({ is_low_confidence: true })]);
    expect(row.lowConfidence).toBe(true);
  });

  it("flattens component ages into keyed fields", () => {
    const [row] = toChartRows([point()]);
    expect(row.componentAges.kdm).toBeCloseTo(34.0);
    expect(row.componentAges.hrv_norm).toBeCloseTo(32.0);
  });

  it("preserves input order", () => {
    const rows = toChartRows([
      point({ week_start: "2026-06-01" }),
      point({ week_start: "2026-06-08" }),
    ]);
    expect(rows.map((r) => r.week)).toEqual(["2026-06-01", "2026-06-08"]);
  });

  it("tolerates a point with no components", () => {
    const [row] = toChartRows([point({ components: [] })]);
    expect(row.componentAges).toEqual({});
  });
});

describe("componentKeys", () => {
  it("returns the union of component names across all points", () => {
    const keys = componentKeys([
      point({ components: [{ component: "kdm", age_years: 1, sigma_years: 1, inputs: {} }] }),
      point({ components: [{ component: "ntnu_fitness", age_years: 1, sigma_years: 1, inputs: {} }] }),
    ]);
    expect(keys.sort()).toEqual(["kdm", "ntnu_fitness"]);
  });

  it("deduplicates", () => {
    expect(componentKeys([point(), point()]).sort()).toEqual(["hrv_norm", "kdm"]);
  });
});

describe("formatYears", () => {
  it("shows one decimal place", () => {
    expect(formatYears(33.847)).toBe("33.8 yr");
  });

  it("renders a dash for null", () => {
    expect(formatYears(null)).toBe("—");
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npm install && npm test`
Expected: FAIL — cannot resolve `../src/lib/series`

- [ ] **Step 4: Implement types, client and transform**

`frontend/src/api/types.ts`:
```typescript
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

export interface SyncStatus {
  connected: boolean;
  data_types: CoverageRow[];
}
```

`frontend/src/api/client.ts`:
```typescript
import type { Measurement, Profile, SeriesPoint, SyncStatus, WeekDetail } from "./types";

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
export const getWeek = (week: string) => request<WeekDetail>(`/api/bioage/weeks/${week}`);
export const getProfile = () => request<Profile>("/api/profile");
export const getSyncStatus = () => request<SyncStatus>("/api/sync/status");
export const triggerSync = () => request<unknown>("/api/sync", { method: "POST" });

export const putProfile = (sex: string, birthdate: string) =>
  request<Profile>("/api/profile", {
    method: "PUT",
    body: JSON.stringify({ sex, birthdate }),
  });

export const addMeasurement = (kind: string, value: number, measuredOn: string) =>
  request<Measurement>("/api/profile/measurements", {
    method: "POST",
    body: JSON.stringify({ kind, value, measured_on: measuredOn }),
  });

export const deleteMeasurement = (id: number) =>
  request<void>(`/api/profile/measurements/${id}`, { method: "DELETE" });

export const authStartUrl = () => `${BASE}/api/auth/google/start`;
```

`frontend/src/lib/series.ts`:
```typescript
import type { SeriesPoint } from "../api/types";

export interface ChartRow {
  week: string;
  bioAge: number;
  chronoAge: number;
  ciLow: number;
  ciHigh: number;
  /** Recharts renders a shaded band from a [low, high] tuple. */
  band: [number, number];
  lowConfidence: boolean;
  componentAges: Record<string, number>;
}

export function toChartRows(points: SeriesPoint[]): ChartRow[] {
  return points.map((point) => ({
    week: point.week_start,
    bioAge: point.composite_age,
    chronoAge: point.chronological_age,
    ciLow: point.ci_low,
    ciHigh: point.ci_high,
    band: [point.ci_low, point.ci_high],
    lowConfidence: point.is_low_confidence,
    componentAges: Object.fromEntries(
      point.components.map((c) => [c.component, c.age_years]),
    ),
  }));
}

export function componentKeys(points: SeriesPoint[]): string[] {
  const keys = new Set<string>();
  for (const point of points) {
    for (const component of point.components) keys.add(component.component);
  }
  return [...keys];
}

export function formatYears(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value.toFixed(1)} yr`;
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npm test`
Expected: PASS — 12 passed

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/tsconfig.json \
        frontend/vite.config.ts frontend/index.html frontend/src/api frontend/src/lib \
        frontend/tests
git commit -m "feat: frontend scaffold, typed API client and chart series transform"
```

---

### Task 26: Dashboard chart

**Files:**
- Create: `frontend/src/components/BioAgeChart.tsx`
- Create: `frontend/src/components/MethodologyNote.tsx`
- Create: `frontend/src/pages/Dashboard.tsx`
- Create: `frontend/src/App.tsx`, `frontend/src/main.tsx`, `frontend/src/styles.css`
- Create: `frontend/tests/BioAgeChart.test.tsx`

**Interfaces:**
- Consumes: `toChartRows`, `componentKeys`, `getSeries`
- Produces: `<BioAgeChart points={SeriesPoint[]} visibleComponents={string[]} />` and `<Dashboard />`

> **Before writing the chart, invoke the `dataviz` skill** and follow its guidance on
> palette, axis treatment, and legend. Do not freehand the visual design.

- [ ] **Step 1: Write the failing test**

`frontend/tests/BioAgeChart.test.tsx`:
```typescript
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BioAgeChart } from "../src/components/BioAgeChart";
import type { SeriesPoint } from "../src/api/types";

const points: SeriesPoint[] = [
  {
    week_start: "2026-06-01",
    chronological_age: 36.2,
    composite_age: 33.8,
    ci_low: 28.1,
    ci_high: 39.5,
    is_low_confidence: false,
    components: [{ component: "kdm", age_years: 34.0, sigma_years: 6.5, inputs: {} }],
  },
  {
    week_start: "2026-06-08",
    chronological_age: 36.2,
    composite_age: 33.1,
    ci_low: 27.5,
    ci_high: 38.7,
    is_low_confidence: true,
    components: [{ component: "kdm", age_years: 33.5, sigma_years: 6.5, inputs: {} }],
  },
];

describe("BioAgeChart", () => {
  it("renders an empty state when there are no points", () => {
    render(<BioAgeChart points={[]} visibleComponents={[]} />);
    expect(screen.getByText(/no biological age data yet/i)).toBeDefined();
  });

  it("renders a chart region when points exist", () => {
    const { container } = render(
      <BioAgeChart points={points} visibleComponents={[]} />,
    );
    expect(container.querySelector(".recharts-responsive-container")).not.toBeNull();
  });

  it("labels the y axis in years", () => {
    render(<BioAgeChart points={points} visibleComponents={[]} />);
    expect(screen.getByText(/age \(years\)/i)).toBeDefined();
  });

  it("does not crash when a component series is toggled on", () => {
    const { container } = render(
      <BioAgeChart points={points} visibleComponents={["kdm"]} />,
    );
    expect(container.querySelector(".recharts-responsive-container")).not.toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — cannot resolve `../src/components/BioAgeChart`

- [ ] **Step 3: Invoke the dataviz skill**

Load the `dataviz` skill and follow its palette and layout guidance for the chart below.
Substitute its recommended colors for the placeholders in `COMPONENT_COLORS`.

- [ ] **Step 4: Implement the chart**

`frontend/src/components/BioAgeChart.tsx`:
```tsx
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { SeriesPoint } from "../api/types";
import { formatYears, toChartRows } from "../lib/series";

/** Replace with the dataviz skill's palette. */
const COMPONENT_COLORS: Record<string, string> = {
  kdm: "#7c6cf0",
  ntnu_fitness: "#3fa7a0",
  hrv_norm: "#d98b3f",
  steps_mortality: "#b45c8f",
};

const COMPONENT_LABELS: Record<string, string> = {
  kdm: "KDM",
  ntnu_fitness: "Fitness age (NTNU)",
  hrv_norm: "HRV age",
  steps_mortality: "Step-count age",
};

interface Props {
  points: SeriesPoint[];
  visibleComponents: string[];
}

export function BioAgeChart({ points, visibleComponents }: Props) {
  if (points.length === 0) {
    return (
      <div className="empty-state">
        <p>No biological age data yet.</p>
        <p className="muted">
          Connect Google Health and sync, or seed demo data to see the chart.
        </p>
      </div>
    );
  }

  const rows = toChartRows(points).map((row) => ({
    ...row,
    ...Object.fromEntries(
      Object.entries(row.componentAges).map(([key, value]) => [`c_${key}`, value]),
    ),
    lowConfidencePoint: row.lowConfidence ? row.bioAge : undefined,
  }));

  return (
    <ResponsiveContainer width="100%" height={420}>
      <ComposedChart data={rows} margin={{ top: 16, right: 24, bottom: 24, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" opacity={0.25} />
        <XAxis dataKey="week" tick={{ fontSize: 12 }} minTickGap={28} />
        <YAxis
          tick={{ fontSize: 12 }}
          domain={["dataMin - 3", "dataMax + 3"]}
          label={{ value: "Age (years)", angle: -90, position: "insideLeft", fontSize: 12 }}
        />
        <Tooltip
          formatter={(value: number, name: string) => [formatYears(value), name]}
          labelFormatter={(label: string) => `Week of ${label}`}
        />
        <Legend />

        <Area
          dataKey="band"
          name="95% interval"
          stroke="none"
          fill="#7c6cf0"
          fillOpacity={0.15}
          isAnimationActive={false}
        />
        <Line
          dataKey="chronoAge"
          name="Chronological age"
          stroke="#8a8f98"
          strokeDasharray="6 4"
          dot={false}
          isAnimationActive={false}
        />
        <Line
          dataKey="bioAge"
          name="Biological age"
          stroke="#7c6cf0"
          strokeWidth={2.5}
          dot={{ r: 3 }}
          isAnimationActive={false}
        />
        {/* Thin weeks get a hollow marker so low confidence is visible, not just encoded. */}
        <Scatter
          dataKey="lowConfidencePoint"
          name="Low data coverage"
          fill="#ffffff"
          stroke="#7c6cf0"
          shape="circle"
        />

        {visibleComponents.map((key) => (
          <Line
            key={key}
            dataKey={`c_${key}`}
            name={COMPONENT_LABELS[key] ?? key}
            stroke={COMPONENT_COLORS[key] ?? "#999999"}
            strokeWidth={1.5}
            dot={false}
            opacity={0.85}
            isAnimationActive={false}
          />
        ))}
      </ComposedChart>
    </ResponsiveContainer>
  );
}
```

`frontend/src/components/MethodologyNote.tsx`:
```tsx
export function MethodologyNote() {
  return (
    <aside className="methodology-note">
      <strong>How to read this.</strong> This is a fitness and autonomic proxy, not a
      validated aging clock. Absolute values carry error bars of several years — the
      shaded band is a 95% interval — and the <em>trend</em> is far more reliable than any
      single point. Hollow markers mark weeks with thin data coverage. See{" "}
      <code>docs/METHODOLOGY.md</code> for every equation, constant and caveat.
    </aside>
  );
}
```

`frontend/src/pages/Dashboard.tsx`:
```tsx
import { useEffect, useState } from "react";

import { getSeries } from "../api/client";
import type { SeriesPoint } from "../api/types";
import { BioAgeChart } from "../components/BioAgeChart";
import { MethodologyNote } from "../components/MethodologyNote";
import { componentKeys, formatYears } from "../lib/series";

export function Dashboard() {
  const [points, setPoints] = useState<SeriesPoint[]>([]);
  const [visible, setVisible] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getSeries()
      .then(setPoints)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const latest = points.at(-1);
  const keys = componentKeys(points);

  const toggle = (key: string) =>
    setVisible((current) =>
      current.includes(key) ? current.filter((k) => k !== key) : [...current, key],
    );

  if (loading) return <p>Loading…</p>;
  if (error) return <p className="error">Could not load series: {error}</p>;

  return (
    <section>
      <header className="dashboard-header">
        <h1>Biological age</h1>
        {latest && (
          <p className="headline">
            <strong>{formatYears(latest.composite_age)}</strong> vs{" "}
            {formatYears(latest.chronological_age)} chronological
            <span className="muted">
              {" "}
              ({formatYears(latest.ci_low)}–{formatYears(latest.ci_high)})
            </span>
          </p>
        )}
      </header>

      <BioAgeChart points={points} visibleComponents={visible} />

      {keys.length > 0 && (
        <div className="component-toggles">
          <span className="muted">Show components:</span>
          {keys.map((key) => (
            <label key={key}>
              <input
                type="checkbox"
                checked={visible.includes(key)}
                onChange={() => toggle(key)}
              />
              {key}
            </label>
          ))}
        </div>
      )}

      <MethodologyNote />
    </section>
  );
}
```

`frontend/src/App.tsx`:
```tsx
import { NavLink, Route, Routes } from "react-router-dom";

import { Connection } from "./pages/Connection";
import { Dashboard } from "./pages/Dashboard";
import { ProfilePage } from "./pages/Profile";

export function App() {
  return (
    <div className="app">
      <nav>
        <NavLink to="/">Dashboard</NavLink>
        <NavLink to="/profile">Profile</NavLink>
        <NavLink to="/connection">Connection</NavLink>
      </nav>
      <main>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/connection" element={<Connection />} />
        </Routes>
      </main>
    </div>
  );
}
```

`frontend/src/main.tsx`:
```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
```

`frontend/src/styles.css`:
```css
:root {
  --bg: #14151a;
  --fg: #e8e9ed;
  --muted: #8a8f98;
  --accent: #7c6cf0;
  --border: #2a2c35;
  color-scheme: dark;
}

body {
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif;
}

.app { max-width: 1100px; margin: 0 auto; padding: 24px; }

nav { display: flex; gap: 20px; border-bottom: 1px solid var(--border); padding-bottom: 12px; }
nav a { color: var(--muted); text-decoration: none; }
nav a.active { color: var(--fg); font-weight: 600; }

main { padding-top: 24px; }
h1 { font-size: 22px; margin: 0 0 4px; }
.headline { font-size: 17px; margin: 0 0 20px; }
.muted { color: var(--muted); }
.error { color: #e5776b; }

.empty-state {
  border: 1px dashed var(--border);
  border-radius: 10px;
  padding: 56px 24px;
  text-align: center;
}

.component-toggles { display: flex; gap: 16px; flex-wrap: wrap; margin: 16px 0; font-size: 13px; }
.component-toggles label { display: flex; gap: 6px; align-items: center; }

.methodology-note {
  margin-top: 24px;
  padding: 14px 16px;
  border-left: 3px solid var(--accent);
  background: rgba(124, 108, 240, 0.08);
  border-radius: 0 8px 8px 0;
  font-size: 13px;
}

table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); }
th { color: var(--muted); font-weight: 500; }

button {
  background: var(--accent); color: #fff; border: 0; border-radius: 7px;
  padding: 8px 16px; font-size: 14px; cursor: pointer;
}
button:disabled { opacity: 0.5; cursor: default; }

input, select {
  background: #1c1e26; color: var(--fg); border: 1px solid var(--border);
  border-radius: 6px; padding: 7px 9px; font-size: 14px;
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npm test`
Expected: PASS — 16 passed

> If Task 27's pages do not exist yet, temporarily stub `Connection` and `ProfilePage`
> as `export function X() { return null; }` so `App.tsx` compiles, then complete them in
> Task 27.

- [ ] **Step 6: Commit**

```bash
git add frontend/src frontend/tests
git commit -m "feat: biological age chart with confidence band and component toggles"
```

---

### Task 27: Profile and Connection pages

**Files:**
- Create: `frontend/src/pages/Profile.tsx`
- Create: `frontend/src/pages/Connection.tsx`
- Create: `frontend/src/components/MeasurementTable.tsx`
- Create: `frontend/src/components/CoverageTable.tsx`
- Create: `frontend/tests/MeasurementTable.test.tsx`

**Interfaces:**
- Consumes: `getProfile`, `putProfile`, `addMeasurement`, `deleteMeasurement`, `getSyncStatus`, `triggerSync`, `authStartUrl`
- Produces: `<ProfilePage />`, `<Connection />`, `<MeasurementTable measurements onDelete />`, `<CoverageTable rows />`

- [ ] **Step 1: Write the failing test**

`frontend/tests/MeasurementTable.test.tsx`:
```typescript
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MeasurementTable } from "../src/components/MeasurementTable";
import type { Measurement } from "../src/api/types";

const measurements: Measurement[] = [
  { id: 1, kind: "waist_cm", value: 88, measured_on: "2026-05-01" },
  { id: 2, kind: "waist_cm", value: 86, measured_on: "2026-07-01" },
];

describe("MeasurementTable", () => {
  it("shows a prompt when there are no measurements", () => {
    render(<MeasurementTable measurements={[]} onDelete={vi.fn()} />);
    expect(screen.getByText(/no measurements recorded/i)).toBeDefined();
  });

  it("renders one row per measurement", () => {
    render(<MeasurementTable measurements={measurements} onDelete={vi.fn()} />);
    expect(screen.getAllByRole("row")).toHaveLength(3); // header + 2
  });

  it("shows the measurement date so history is visible", () => {
    render(<MeasurementTable measurements={measurements} onDelete={vi.fn()} />);
    expect(screen.getByText("2026-05-01")).toBeDefined();
    expect(screen.getByText("2026-07-01")).toBeDefined();
  });

  it("calls onDelete with the row id", () => {
    const onDelete = vi.fn();
    render(<MeasurementTable measurements={measurements} onDelete={onDelete} />);
    fireEvent.click(screen.getAllByRole("button", { name: /remove/i })[0]);
    expect(onDelete).toHaveBeenCalledWith(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — cannot resolve `../src/components/MeasurementTable`

- [ ] **Step 3: Implement the components and pages**

`frontend/src/components/MeasurementTable.tsx`:
```tsx
import type { Measurement } from "../api/types";

const LABELS: Record<Measurement["kind"], string> = {
  height_m: "Height (m)",
  weight_kg: "Weight (kg)",
  waist_cm: "Waist (cm)",
};

interface Props {
  measurements: Measurement[];
  onDelete: (id: number) => void;
}

export function MeasurementTable({ measurements, onDelete }: Props) {
  if (measurements.length === 0) {
    return <p className="muted">No measurements recorded yet.</p>;
  }
  return (
    <table>
      <thead>
        <tr>
          <th>Measurement</th>
          <th>Value</th>
          <th>Measured on</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {measurements.map((m) => (
          <tr key={m.id}>
            <td>{LABELS[m.kind]}</td>
            <td>{m.value}</td>
            <td>{m.measured_on}</td>
            <td>
              <button onClick={() => onDelete(m.id)} aria-label={`Remove ${LABELS[m.kind]}`}>
                Remove
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

`frontend/src/components/CoverageTable.tsx`:
```tsx
import type { CoverageRow } from "../api/types";

export function CoverageTable({ rows }: { rows: CoverageRow[] }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Data type</th>
          <th>Points stored</th>
          <th>Synced through</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.data_type}>
            <td>{row.data_type}</td>
            <td>{row.points_stored}</td>
            <td>{row.synced_through ?? "—"}</td>
            <td>
              {row.last_error ? (
                <span className="error">{row.last_error}</span>
              ) : row.points_stored === 0 && row.expected_empty ? (
                <span className="muted">empty (expected on the Air)</span>
              ) : row.points_stored === 0 ? (
                <span className="muted">no data</span>
              ) : (
                "ok"
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

`frontend/src/pages/Profile.tsx`:
```tsx
import { useEffect, useState } from "react";

import { addMeasurement, deleteMeasurement, getProfile, putProfile } from "../api/client";
import type { Measurement, Profile } from "../api/types";
import { MeasurementTable } from "../components/MeasurementTable";

const KINDS: Measurement["kind"][] = ["height_m", "weight_kg", "waist_cm"];

export function ProfilePage() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [sex, setSex] = useState("male");
  const [birthdate, setBirthdate] = useState("");
  const [kind, setKind] = useState<Measurement["kind"]>("waist_cm");
  const [value, setValue] = useState("");
  const [measuredOn, setMeasuredOn] = useState(new Date().toISOString().slice(0, 10));
  const [message, setMessage] = useState<string | null>(null);

  const reload = () =>
    getProfile()
      .then((p) => {
        setProfile(p);
        setSex(p.sex);
        setBirthdate(p.birthdate);
      })
      .catch(() => setProfile(null));

  useEffect(() => {
    void reload();
  }, []);

  const saveProfile = async () => {
    try {
      await putProfile(sex, birthdate);
      setMessage("Profile saved. Scores recomputed.");
      await reload();
    } catch (e) {
      setMessage((e as Error).message);
    }
  };

  const saveMeasurement = async () => {
    try {
      await addMeasurement(kind, Number(value), measuredOn);
      setValue("");
      setMessage("Measurement added. Scores recomputed.");
      await reload();
    } catch (e) {
      setMessage((e as Error).message);
    }
  };

  const remove = async (id: number) => {
    await deleteMeasurement(id);
    await reload();
  };

  return (
    <section>
      <h1>Profile</h1>
      <p className="muted">
        Waist circumference and body size cannot be measured by the band, so they are
        entered here. Measurements are dated: adding a new waist reading today will not
        rewrite past weeks.
      </p>

      <h2>Identity</h2>
      <div className="form-row">
        <select value={sex} onChange={(e) => setSex(e.target.value)}>
          <option value="male">Male</option>
          <option value="female">Female</option>
        </select>
        <input
          type="date"
          value={birthdate}
          onChange={(e) => setBirthdate(e.target.value)}
          aria-label="Birthdate"
        />
        <button onClick={saveProfile} disabled={!birthdate}>
          Save
        </button>
      </div>

      <h2>Measurements</h2>
      <div className="form-row">
        <select value={kind} onChange={(e) => setKind(e.target.value as Measurement["kind"])}>
          {KINDS.map((k) => (
            <option key={k} value={k}>
              {k}
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
        <button onClick={saveMeasurement} disabled={!value}>
          Add
        </button>
      </div>

      <MeasurementTable measurements={profile?.measurements ?? []} onDelete={remove} />
      {message && <p className="muted">{message}</p>}
    </section>
  );
}
```

`frontend/src/pages/Connection.tsx`:
```tsx
import { useEffect, useState } from "react";

import { authStartUrl, getSyncStatus, triggerSync } from "../api/client";
import type { SyncStatus } from "../api/types";
import { CoverageTable } from "../components/CoverageTable";

export function Connection() {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const reload = () => getSyncStatus().then(setStatus).catch(() => setStatus(null));

  useEffect(() => {
    void reload();
  }, []);

  const sync = async () => {
    setSyncing(true);
    setMessage(null);
    try {
      await triggerSync();
      setMessage("Sync complete.");
      await reload();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setSyncing(false);
    }
  };

  return (
    <section>
      <h1>Connection</h1>
      {status?.connected ? (
        <p>Connected to Google Health.</p>
      ) : (
        <p>
          Not connected.{" "}
          <a href={authStartUrl()}>Connect Google Health</a> — see{" "}
          <code>docs/SETUP.md</code> if this returns an error.
        </p>
      )}

      <button onClick={sync} disabled={!status?.connected || syncing}>
        {syncing ? "Syncing…" : "Sync now"}
      </button>
      {message && <p className="muted">{message}</p>}

      <h2>Data coverage</h2>
      <p className="muted">
        The Fitbit Air does not produce VO<sub>2</sub>max, so that row is expected to stay
        empty.
      </p>
      <CoverageTable rows={status?.data_types ?? []} />
    </section>
  );
}
```

- [ ] **Step 4: Run tests and the type check**

Run: `cd frontend && npm test && npm run lint`
Expected: PASS — 20 passed, and `tsc --noEmit` reports no errors.

- [ ] **Step 5: Verify the app renders against the live backend**

Run:
```bash
docker compose up -d --build
docker compose exec backend uv run python -m bioage.cli seed-demo --days 400
```
Then open http://localhost:5173 and confirm:
- the chart renders a biological age line with a shaded band and a dashed chronological-age line
- toggling a component checkbox adds a series
- the Profile page lists the three demo measurements
- the Connection page shows "Not connected" and a coverage table with `daily-vo2-max` at 0

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages frontend/src/components frontend/tests
git commit -m "feat: profile and connection pages with coverage diagnostics"
```

---

## Phase J — Documentation

### Task 28: Methodology documentation

**Files:**
- Create: `docs/METHODOLOGY.md`

**Interfaces:**
- Consumes: every reference YAML and estimator module
- Produces: no code — the document that makes the project defensible as open source.

- [ ] **Step 1: Write the methodology document**

`docs/METHODOLOGY.md` must contain, in this order:

1. **What this is and is not** — a fitness/autonomic proxy, not a validated aging clock;
   error bars of several years; trend over absolute value.
2. **Inputs** — the exact data types consumed, which are primary (RHR, HRV RMSSD, steps,
   sleep) and which are trend-only (SpO₂, skin temperature), and which are user-supplied
   (sex, birthdate, height, weight, waist).
3. **Feature window** — 30-day trailing medians; coverage gates (`MIN_WINDOW_DAYS=14`,
   `LOW_CONFIDENCE_DAYS=21`, per-biomarker minimums); why medians not means.
4. **Each estimator**, with its equation written out, its citation, its σ and where that σ
   came from, and its failure modes. Copy the equations verbatim from the source modules
   so the document cannot drift from the code.
5. **The composite** — the inverse-variance formula, the σ multipliers and why HRV is
   downweighted, the 1.96 z-score, and the low-confidence inflation factor.
6. **Known approximations**, each under its own heading:
   - *The PA index is not the HUNT questionnaire index.* Explain the steps→index mapping,
     show the knot table, and state that this is the weakest input in the NTNU estimator.
   - *KDM reference constants are derived, not primary.* Explain that no published NHANES
     q/k/s table exists for wearable biomarkers, that the constants come from OLS on
     published age-stratified normative tables via `regenerate_kdm.py`, and that this makes
     the estimator "KDM-style" rather than published NHANES KDM.
   - *Reference-population sensitivity.* Changing `reference_population` in `ntnu.yaml`
     shifts every fitness age by a constant offset.
   - *Wrist PPG HRV noise.* MAPE frequently above 10% against ECG.
   - *Sleep efficiency and WASO are derived*, not reported by the API.
7. **Reproducing the constants** — the exact command
   `uv run python -m bioage.reference.regenerate_kdm` and how to audit the normative
   tables it uses.
8. **Correction to the source research** — document that
   `reference-research-from-claude.md` prints the KDM denominator as `Σ(kⱼ/sⱼ²)²`, that
   this fails the identity `BA_E = A` for a subject on the reference regression, and that
   the implementation uses `Σ kⱼ²/sⱼ²`. Reference the guard test in
   `tests/estimators/test_kdm.py`.

- [ ] **Step 2: Verify every constant in the document matches the code**

Run:
```bash
cd backend && uv run python -c "
from bioage.reference.loader import get_composite, get_hrv_norms, get_kdm, get_ntnu, get_pa_index
for name, fn in [('ntnu', get_ntnu), ('pa_index', get_pa_index), ('hrv', get_hrv_norms),
                 ('kdm', get_kdm), ('composite', get_composite)]:
    c = fn()
    print(f'--- {name} (derived={c.derived}) ---')
    print(c.model_dump_json(indent=2))
"
```
Cross-check each printed value against the document. Any mismatch means the document is
wrong, not the code.

- [ ] **Step 3: Commit**

```bash
git add docs/METHODOLOGY.md
git commit -m "docs: methodology with every equation, constant, citation and caveat"
```

---

### Task 29: Setup guide and README

**Files:**
- Create: `docs/SETUP.md`
- Create: `README.md`

**Interfaces:**
- Consumes: everything
- Produces: the user-facing instructions requested in the original brief.

- [ ] **Step 1: Write the setup guide**

`docs/SETUP.md` — written for someone who has never opened Google Cloud Console. It must
walk through, with the exact values to type:

1. **Prerequisites** — Docker Desktop, a Google Account with the Fitbit Air paired to the
   Google Health app, and confirmation that the band has synced recently (data appears
   only after the phone syncs).
2. **Try it first without credentials** —
   `cp .env.example .env`, `docker compose up -d --build`,
   `docker compose exec backend uv run alembic upgrade head`,
   `docker compose exec backend uv run python -m bioage.cli seed-demo`,
   then open http://localhost:5173. This proves the stack works before any Google setup.
3. **Create a Google Cloud project** — console.cloud.google.com → project picker → New
   Project → name it → Create.
4. **Enable the Google Health API** — APIs & Services → Library → search "Google Health
   API" → Enable. Note: this is *not* "Google Fit API", which is deprecated.
5. **Configure the OAuth consent screen** — External; app name; your own email as both
   support and developer contact; **add your own Google account under Test users** (without
   this, the flow fails with `access_denied`); Save.
6. **Add scopes** — Add or Remove Scopes → paste each of the three read scopes:
   - `https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly`
   - `https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly`
   - `https://www.googleapis.com/auth/googlehealth.sleep.readonly`
7. **Create the OAuth client** — Credentials → Create Credentials → OAuth client ID →
   Application type **Web application** → Authorized redirect URI exactly
   `http://localhost:8000/api/auth/google/callback` → Create → copy the Client ID and
   Client secret.
8. **Fill in `.env`** — set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, then
   `docker compose restart backend`.
9. **Connect and sync** — open http://localhost:5173/connection → Connect Google Health →
   approve (the "Google hasn't verified this app" warning is expected for your own
   unpublished app; choose Advanced → Continue) → Sync now.
10. **Enter your profile** — http://localhost:5173/profile: sex, birthdate, height, weight,
    and **waist circumference measured at the navel with a tape measure**, since the NTNU
    equation depends on it and nothing can measure it for you.
11. **Optional automatic sync** — set `SYNC_SCHEDULE_ENABLED=true` and restart.

Plus a **Troubleshooting** section covering, with the cause and fix for each:
- `503` from `/api/auth/google/start` → credentials not set in `.env`, or backend not restarted
- `access_denied` → your account is not in Test users
- `redirect_uri_mismatch` → the URI in Cloud Console differs by a character from `OAUTH_REDIRECT_URI`
- `403 insufficient scope` → a scope was missed; revoke access at
  myaccount.google.com/permissions and reconnect
- "Google did not return a refresh token" → revoke access as above and reconnect so consent re-prompts
- Empty `daily-vo2-max` → expected on the Air; not an error
- Few or no weekly points → the band needs roughly 14 days of data before the first score
- `429` in sync logs → rate limited; the client retries automatically, just wait

- [ ] **Step 2: Write the README**

`README.md` must cover: what the project does; a screenshot placeholder of the chart; the
honest framing paragraph; a quickstart pointing at demo mode; a link to `docs/SETUP.md`
and `docs/METHODOLOGY.md`; the architecture diagram in text form; how to run the tests
(`cd backend && uv run pytest`, `cd frontend && npm test`); and a licence note.

- [ ] **Step 3: Verify the setup guide by following it from scratch**

Run:
```bash
docker compose down -v
cp .env.example .env
docker compose up -d --build
docker compose exec backend uv run alembic upgrade head
docker compose exec backend uv run python -m bioage.cli seed-demo
```
Then open http://localhost:5173 and confirm the chart renders. Every command in Step 2 of
the guide must work verbatim from a clean state — if one does not, fix the guide.

- [ ] **Step 4: Final full verification**

Run:
```bash
cd backend && uv run pytest -v && uv run ruff check src tests \
  && uv run mypy src/bioage/estimators src/bioage/biomarkers
cd ../frontend && npm test && npm run lint && npm run build
```
Expected: all backend tests pass, no lint or type errors, all frontend tests pass, and the
production build succeeds.

- [ ] **Step 5: Commit**

```bash
git add docs/SETUP.md README.md
git commit -m "docs: step-by-step Google Cloud setup guide and README"
```

---

## Verification Checklist

Before declaring the project complete, confirm each of these by running the command and
reading the output — not by assuming:

- [ ] `cd backend && uv run pytest` — every test passes
- [ ] `cd backend && uv run ruff check src tests` — clean
- [ ] `cd backend && uv run mypy src/bioage/estimators src/bioage/biomarkers` — clean
- [ ] `cd frontend && npm test && npm run lint && npm run build` — clean
- [ ] `docker compose down -v && docker compose up -d --build` then seed demo — chart renders at localhost:5173
- [ ] Every YAML in `reference/` has a `source` on every constant set
- [ ] `grep -rn "from bioage.db\|from bioage.api\|from bioage.ingest" backend/src/bioage/estimators/` returns nothing
- [ ] `docs/METHODOLOGY.md` constants match `uv run python -c "..."` output from Task 28 Step 2
- [ ] Every command in `docs/SETUP.md` runs verbatim from a clean checkout
