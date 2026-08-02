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

# Non-wear stretches: a real wearable is set down for days at a time (forgotten charge,
# travel, a broken band) rather than dropped independently night to night. The first
# stretch never starts before this offset, so a short demo history (as used for early
# scoring windows) is fully populated while a longer one still exercises gap handling.
GAP_EARLIEST_OFFSET = 210


def _gap_blocks(days: int, rng: random.Random) -> list[tuple[int, int]]:
    """Contiguous unworn day ranges, as half-open [start, end) offsets from day 0."""
    blocks: list[tuple[int, int]] = []
    cursor = GAP_EARLIEST_OFFSET + rng.randint(0, 20)
    while cursor < days:
        length = rng.randint(4, 10)
        blocks.append((cursor, min(cursor + length, days)))
        cursor += length + 110 + rng.randint(0, 30)
    return blocks


def generate_daily_metrics(
    start: date,
    days: int,
    seed: int = DEMO_SEED,
) -> list[DailyMetric]:
    """Produce `days` consecutive DailyMetric rows with realistic structure and gaps."""
    rng = random.Random(seed)
    gap_blocks = _gap_blocks(days, rng)
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

        # Realistic gaps: the band is set down for whole stretches, not single nights.
        in_gap = any(block_start <= offset < block_end for block_start, block_end in gap_blocks)
        wore_device = not in_gap
        got_hrv = not in_gap

        metrics.append(
            DailyMetric(
                date=day,
                resting_hr_bpm=(
                    round(max(40.0, min(100.0, resting_hr)), 1) if wore_device else None
                ),
                hrv_rmssd_ms=round(max(5.0, min(150.0, rmssd)), 1) if got_hrv else None,
                hrv_average_ms=(
                    round(max(5.0, min(150.0, rmssd * 0.92)), 1) if got_hrv else None
                ),
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
            )
        )

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
