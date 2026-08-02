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

from typing import Any

from bioage.biomarkers.parsers.common import parse_duration_seconds, parse_timestamp
from bioage.biomarkers.parsers.daily import ParsedPoint

ASLEEP_STAGES = ("LIGHT", "DEEP", "REM")


def parse_sleep(payload: dict[str, Any]) -> ParsedPoint | None:
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

    summary = body.get("sleepSummary")
    if not isinstance(summary, dict):
        summary = {}
    total_raw = summary.get("totalDuration")
    total_min = parse_duration_seconds(total_raw) / 60.0 if total_raw else time_in_bed_min

    midpoint = start + (end - start) / 2
    values: dict[str, float] = {
        "sleep_total_min": total_min,
        "sleep_midpoint_local_min": midpoint.hour * 60.0 + midpoint.minute + midpoint.second / 60.0,
    }

    metadata = body.get("sleepMetadata")
    stages_available = (
        isinstance(metadata, dict) and metadata.get("stagesState") == "STAGES_AVAILABLE"
    )
    stage_summary = summary.get("stageSummary")
    if stages_available and isinstance(stage_summary, list):
        durations: dict[str, float] = {}
        for entry in stage_summary:
            if not isinstance(entry, dict):
                continue
            stage = entry.get("stage")
            duration = entry.get("duration")
            if stage and duration:
                durations[stage] = durations.get(stage, 0.0) + parse_duration_seconds(duration)

        asleep_seconds = sum(durations.get(stage, 0.0) for stage in ASLEEP_STAGES)
        # Clamped to [0, 100]: stage durations are reported independently of the
        # session interval, so a device that reports slightly more asleep-stage time
        # than the session spans (clock drift between the two, or a stage that
        # overruns the session boundary) would otherwise produce >100% efficiency --
        # arithmetically valid here, but meaningless, and it flows straight into KDM
        # as a biomarker (bioage.estimators.kdm), where an implausible value skews the
        # estimate rather than just looking wrong in a UI.
        efficiency = asleep_seconds / 60.0 / time_in_bed_min * 100.0
        values["sleep_efficiency_pct"] = min(max(efficiency, 0.0), 100.0)

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
        index
        for index, stage in enumerate(stages)
        if isinstance(stage, dict) and stage.get("stage") in ASLEEP_STAGES
    ]
    if not asleep_indices:
        return None

    first, last = asleep_indices[0], asleep_indices[-1]
    total = 0.0
    for stage in stages[first : last + 1]:
        if not isinstance(stage, dict) or stage.get("stage") != "AWAKE":
            continue
        start_time = stage.get("startTime")
        end_time = stage.get("endTime")
        if not isinstance(start_time, str) or not isinstance(end_time, str):
            continue
        total += (parse_timestamp(end_time) - parse_timestamp(start_time)).total_seconds() / 60.0
    return total
