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
    return load("sleep")["dataPoints"][0]  # type: ignore[no-any-return]


def test_sleep_is_dated_to_the_wake_date(night: dict[str, Any]) -> None:
    parsed = parse_sleep(night)
    assert parsed is not None
    assert parsed.day == date(2026, 6, 1)


def test_total_duration_is_converted_to_minutes(night: dict[str, Any]) -> None:
    parsed = parse_sleep(night)
    assert parsed is not None
    assert parsed.values["sleep_total_min"] == pytest.approx(480.0)


def test_efficiency_is_asleep_over_time_in_bed(night: dict[str, Any]) -> None:
    # asleep = LIGHT 14400 + DEEP 5400 + REM 6600 = 26400s = 440 min
    # time in bed = 23:00 -> 07:00 = 480 min
    parsed = parse_sleep(night)
    assert parsed is not None
    assert parsed.values["sleep_efficiency_pct"] == pytest.approx(440 / 480 * 100)


def test_waso_excludes_leading_and_trailing_wakefulness(night: dict[str, Any]) -> None:
    """Only the 02:40-03:00 awake block counts; the 10-minute blocks at each end do not."""
    parsed = parse_sleep(night)
    assert parsed is not None
    assert parsed.values["waso_min"] == pytest.approx(20.0)


def test_stage_percentages_are_fractions_of_time_asleep(night: dict[str, Any]) -> None:
    parsed = parse_sleep(night)
    assert parsed is not None
    assert parsed.values["deep_pct"] == pytest.approx(5400 / 26400 * 100)
    assert parsed.values["rem_pct"] == pytest.approx(6600 / 26400 * 100)


def test_midpoint_is_minutes_past_midnight(night: dict[str, Any]) -> None:
    # 23:00 -> 07:00, midpoint 03:00 = 180 minutes past midnight
    parsed = parse_sleep(night)
    assert parsed is not None
    assert parsed.values["sleep_midpoint_local_min"] == pytest.approx(180.0)


def test_midpoint_handles_a_session_entirely_after_midnight() -> None:
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


def test_night_without_stages_yields_duration_but_no_stage_fields() -> None:
    point = load("sleep_no_stages")["dataPoints"][0]
    parsed = parse_sleep(point)
    assert parsed is not None
    assert parsed.values["sleep_total_min"] == pytest.approx(420.0)
    assert "deep_pct" not in parsed.values
    assert "rem_pct" not in parsed.values
    assert "waso_min" not in parsed.values
    assert "sleep_efficiency_pct" not in parsed.values


def test_returns_none_for_a_non_sleep_payload() -> None:
    assert parse_sleep({"steps": {}}) is None


def test_returns_none_when_the_session_is_missing() -> None:
    assert parse_sleep({"sleep": {"sleepSummary": {"totalDuration": "100s"}}}) is None


def test_zero_length_session_does_not_divide_by_zero() -> None:
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


def test_efficiency_over_100_percent_is_clamped_to_100() -> None:
    """Stage durations are reported independently of the session interval, so a device
    that reports slightly more asleep-stage time than the session spans (clock drift,
    a stage overrunning the session boundary) would otherwise produce an efficiency
    above 100% -- arithmetically valid, biologically meaningless, and this value flows
    straight into KDM as a biomarker."""
    point = {
        "sleep": {
            "session": {
                "startTime": "2026-06-01T01:00:00Z",
                "endTime": "2026-06-01T02:00:00Z",  # 60 minutes in bed
            },
            "sleepMetadata": {"stagesState": "STAGES_AVAILABLE"},
            "sleepSummary": {
                "totalDuration": "3600s",
                "stageSummary": [{"stage": "LIGHT", "duration": "4200s"}],  # 70 minutes
            },
        }
    }
    parsed = parse_sleep(point)
    assert parsed is not None
    assert parsed.values["sleep_efficiency_pct"] == pytest.approx(100.0)


def test_all_awake_night_yields_zero_efficiency_not_a_crash() -> None:
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
                {
                    "startTime": "2026-06-01T01:00:00Z",
                    "endTime": "2026-06-01T03:00:00Z",
                    "stage": "AWAKE",
                }
            ],
        }
    }
    parsed = parse_sleep(point)
    assert parsed is not None
    assert parsed.values["sleep_efficiency_pct"] == pytest.approx(0.0)
    assert "deep_pct" not in parsed.values
