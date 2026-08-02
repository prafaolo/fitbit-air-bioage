from datetime import date, timedelta

import pytest

from bioage.biomarkers.features import (
    LOW_CONFIDENCE_DAYS,
    MIN_HRV_DAYS,
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
    records = (
        make_records(40)
        + [DailyRecord(day=date(2026, 7, 5), resting_hr_bpm=99.0)]
        + [DailyRecord(day=date(2026, 7, 1), resting_hr_bpm=99.0)]
    )
    window = window_records(records, window_end=date(2026, 7, 1))
    assert all(r.day < date(2026, 7, 1) for r in window)
    assert date(2026, 7, 1) not in {r.day for r in window}


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


def test_biomarker_at_exactly_its_own_minimum_is_included_in_the_vector():
    """Exactly MIN_HRV_DAYS nights of HRV must be enough: pins >= vs > in the gate."""
    records = make_records(20)
    thinned = [
        DailyRecord(
            day=r.day,
            resting_hr_bpm=r.resting_hr_bpm,
            hrv_rmssd_ms=r.hrv_rmssd_ms if i < MIN_HRV_DAYS else None,
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
    assert vector.hrv_rmssd_ms is not None


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
    assert compute_coverage(make_records(LOW_CONFIDENCE_DAYS)).is_low_confidence is False
    assert compute_coverage(make_records(WINDOW_DAYS)).is_low_confidence is False
