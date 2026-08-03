import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from bioage.biomarkers.parsers.sleep import parse_sleep

FIXTURES = Path(__file__).parent.parent / "fixtures" / "googlehealth"


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())  # type: ignore[no-any-return]


@pytest.fixture
def night() -> dict[str, Any]:
    """A real captured payload (2026-08-01/02), the sample night documented in
    docs/METHODOLOGY.md §6.5: minutesAsleep=429, minutesInSleepPeriod=432,
    minutesAwake=3, deep=50min, rem=80min, startUtcOffset=+7200s (UTC+2)."""
    return load("sleep")["dataPoints"][0]


@pytest.fixture
def high_waso_night() -> dict[str, Any]:
    """A second real captured payload (2026-07-27/28) with a much higher WASO, to
    exercise a night that isn't a near-perfect sleep."""
    return load("sleep")["dataPoints"][1]


def test_sleep_is_dated_to_the_local_wake_date(night: dict[str, Any]) -> None:
    parsed = parse_sleep(night)
    assert parsed is not None
    assert parsed.day == date(2026, 8, 2)


def test_total_duration_is_minutes_asleep(night: dict[str, Any]) -> None:
    parsed = parse_sleep(night)
    assert parsed is not None
    assert parsed.values["sleep_total_min"] == pytest.approx(429.0)


def test_efficiency_is_asleep_over_minutes_in_sleep_period(night: dict[str, Any]) -> None:
    # 429 / 432 * 100 = 99.30555...
    parsed = parse_sleep(night)
    assert parsed is not None
    assert parsed.values["sleep_efficiency_pct"] == pytest.approx(99.30555555555556)


def test_waso_is_minutes_awake_within_the_sleep_period(night: dict[str, Any]) -> None:
    """minutesToFallAsleep and minutesAfterWakeUp are both 0 in this payload, so
    minutesAwake (3) is already wakefulness within the sleep period -- WASO by
    definition -- with nothing to strip out."""
    parsed = parse_sleep(night)
    assert parsed is not None
    assert parsed.values["waso_min"] == pytest.approx(3.0)


def test_stage_percentages_are_fractions_of_minutes_asleep(night: dict[str, Any]) -> None:
    # deep = 50min, rem = 80min, minutesAsleep = 429min
    parsed = parse_sleep(night)
    assert parsed is not None
    assert parsed.values["deep_pct"] == pytest.approx(11.655011655011654)
    assert parsed.values["rem_pct"] == pytest.approx(18.64801864801865)


def test_midpoint_is_converted_to_local_time_using_the_start_offset(
    night: dict[str, Any],
) -> None:
    # UTC midpoint of 2026-08-01T21:36Z .. 2026-08-02T04:48Z (7h12m span) is
    # 2026-08-02T01:12:00Z. +2h local offset (7200s) -> 03:12 local = 192 minutes
    # past midnight.
    parsed = parse_sleep(night)
    assert parsed is not None
    assert parsed.values["sleep_midpoint_local_min"] == pytest.approx(192.0)


def test_high_waso_night_from_a_second_real_payload(high_waso_night: dict[str, Any]) -> None:
    parsed = parse_sleep(high_waso_night)
    assert parsed is not None
    assert parsed.day == date(2026, 7, 28)
    assert parsed.values["sleep_total_min"] == pytest.approx(337.0)
    assert parsed.values["waso_min"] == pytest.approx(116.0)
    assert parsed.values["sleep_efficiency_pct"] == pytest.approx(74.39293598233996)
    assert parsed.values["deep_pct"] == pytest.approx(26.112759643916917)
    assert parsed.values["rem_pct"] == pytest.approx(15.727002967359049)
    assert parsed.values["sleep_midpoint_local_min"] == pytest.approx(269.5)


def test_a_nap_is_dropped_rather_than_overwriting_the_main_night(
    night: dict[str, Any],
) -> None:
    nap = json.loads(json.dumps(night))
    nap["sleep"]["metadata"]["mainSleep"] = False
    assert parse_sleep(nap) is None


def test_stages_status_other_than_succeeded_omits_stage_derived_keys_only() -> None:
    """duration, efficiency, WASO and midpoint all come from `summary` fields that do
    not depend on per-epoch stage classification, so only deep_pct/rem_pct -- which
    read `stagesSummary` -- are omitted."""
    point = load("sleep_no_stages")["dataPoints"][0]
    parsed = parse_sleep(point)
    assert parsed is not None
    assert parsed.values["sleep_total_min"] == pytest.approx(415.0)
    assert parsed.values["sleep_efficiency_pct"] == pytest.approx(98.80952380952381)
    assert parsed.values["waso_min"] == pytest.approx(5.0)
    assert "deep_pct" not in parsed.values
    assert "rem_pct" not in parsed.values


def test_returns_none_for_a_non_sleep_payload() -> None:
    assert parse_sleep({"steps": {}}) is None


def test_returns_none_when_the_interval_is_missing() -> None:
    point = {
        "sleep": {
            "metadata": {"mainSleep": True},
            "summary": {"minutesAsleep": "10"},
        }
    }
    assert parse_sleep(point) is None


def test_returns_none_when_main_sleep_is_not_true() -> None:
    point = {
        "sleep": {
            "interval": {
                "startTime": "2026-06-01T01:00:00Z",
                "endTime": "2026-06-01T09:00:00Z",
            },
            "metadata": {"processed": True},
            "summary": {"minutesAsleep": "480"},
        }
    }
    assert parse_sleep(point) is None


def test_zero_length_interval_does_not_divide_by_zero() -> None:
    point = {
        "sleep": {
            "interval": {
                "startTime": "2026-06-01T01:00:00Z",
                "endTime": "2026-06-01T01:00:00Z",
                "startUtcOffset": "0s",
                "endUtcOffset": "0s",
            },
            "metadata": {"mainSleep": True, "stagesStatus": "SUCCEEDED"},
            "summary": {"minutesAsleep": "0", "minutesInSleepPeriod": "0"},
        }
    }
    assert parse_sleep(point) is None


def test_efficiency_over_100_percent_is_clamped_to_100() -> None:
    """minutesAsleep and minutesInSleepPeriod are independently reported summary
    fields, so a device that reports slightly more asleep time than the sleep period
    spans would otherwise produce an efficiency above 100% -- arithmetically valid,
    biologically meaningless, and this value flows straight into KDM as a biomarker
    (bioage.estimators.kdm), where an implausible value skews the estimate rather than
    just looking wrong in a UI."""
    point = {
        "sleep": {
            "interval": {
                "startTime": "2026-06-01T01:00:00Z",
                "endTime": "2026-06-01T02:00:00Z",
                "startUtcOffset": "0s",
                "endUtcOffset": "0s",
            },
            "metadata": {"mainSleep": True, "stagesStatus": "SUCCEEDED"},
            "summary": {"minutesAsleep": "70", "minutesInSleepPeriod": "60"},
        }
    }
    parsed = parse_sleep(point)
    assert parsed is not None
    assert parsed.values["sleep_efficiency_pct"] == pytest.approx(100.0)


def test_zero_minutes_asleep_yields_zero_efficiency_and_no_stage_fields() -> None:
    point = {
        "sleep": {
            "interval": {
                "startTime": "2026-06-01T01:00:00Z",
                "endTime": "2026-06-01T03:00:00Z",
                "startUtcOffset": "0s",
                "endUtcOffset": "0s",
            },
            "metadata": {"mainSleep": True, "stagesStatus": "SUCCEEDED"},
            "summary": {
                "minutesAsleep": "0",
                "minutesInSleepPeriod": "120",
                "minutesAwake": "120",
                "stagesSummary": [{"type": "AWAKE", "count": "1", "minutes": "120"}],
            },
        }
    }
    parsed = parse_sleep(point)
    assert parsed is not None
    assert parsed.values["sleep_efficiency_pct"] == pytest.approx(0.0)
    assert "deep_pct" not in parsed.values
    assert "rem_pct" not in parsed.values


def test_midpoint_handles_a_session_entirely_after_midnight_with_zero_offset() -> None:
    point = {
        "sleep": {
            "interval": {
                "startTime": "2026-06-01T01:00:00Z",
                "endTime": "2026-06-01T09:00:00Z",
                "startUtcOffset": "0s",
                "endUtcOffset": "0s",
            },
            "metadata": {"mainSleep": True, "stagesStatus": "FAILED"},
            "summary": {"minutesAsleep": "480", "minutesInSleepPeriod": "480"},
        }
    }
    parsed = parse_sleep(point)
    assert parsed is not None
    assert parsed.values["sleep_midpoint_local_min"] == pytest.approx(300.0)


def test_midpoint_applies_a_negative_local_offset() -> None:
    """UTC midpoint of 01:00-09:00 is 05:00Z; a UTC-5 offset shifts local time to
    00:00, i.e. 0 minutes past midnight."""
    point = {
        "sleep": {
            "interval": {
                "startTime": "2026-06-01T01:00:00Z",
                "endTime": "2026-06-01T09:00:00Z",
                "startUtcOffset": "-18000s",
                "endUtcOffset": "-18000s",
            },
            "metadata": {"mainSleep": True, "stagesStatus": "FAILED"},
            "summary": {"minutesAsleep": "480", "minutesInSleepPeriod": "480"},
        }
    }
    parsed = parse_sleep(point)
    assert parsed is not None
    assert parsed.values["sleep_midpoint_local_min"] == pytest.approx(0.0)
    assert parsed.day == date(2026, 6, 1)  # 09:00 UTC - 5h = 04:00 local, same day
