"""Sleep parsing.

Earlier versions of this parser were built against Google's RPC reference docs, which
describe a `session`/`sleepSummary`/`sleepStages` shape that the live API does not
actually send. The real payload nests everything under `interval`/`summary`/`stages`
and, unlike the documented shape, already reports sleep efficiency's inputs and WASO
directly -- there is no need to re-derive them from the stage timeline by hand:

    sleep_total_min      = summary.minutesAsleep
    sleep_efficiency_pct = minutesAsleep / minutesInSleepPeriod * 100, clamped to [0, 100]
    waso_min             = summary.minutesAwake
    deep_pct / rem_pct   = that stage's summary.stagesSummary[].minutes, as a percentage
                           of minutesAsleep

`minutesAwake` is safe to use directly as WASO: the payload separates onset latency
(`minutesToFallAsleep`) and post-wake time (`minutesAfterWakeUp`) from time asleep, so
`minutesAwake` is already wakefulness *within* the sleep period -- which is what WASO
means -- with no leading/trailing-wakefulness contamination to strip out by hand.

`interval.startUtcOffset` carries the session's real local UTC offset, so the midpoint
is converted to genuine local time here. This resolves the DST limitation documented in
`docs/METHODOLOGY.md` §6.5: the old parser had no local offset to work with and read
each timestamp's own (UTC) offset, so a DST transition inside a rolling window injected
a spurious ~60-minute shift into the regularity statistic. That limitation no longer
applies now that a genuine local offset is available per session.

A night is attributed to the local wake date (local `interval.endTime`). Only
`metadata.mainSleep == true` records are accepted -- naps are dropped rather than
overwriting the main night's row for that date. When `metadata.stagesStatus` is not
`"SUCCEEDED"`, the stage-derived keys (`deep_pct`, `rem_pct`) are omitted; duration,
efficiency, WASO and midpoint all come from `summary` fields that do not depend on
per-epoch stage classification having succeeded.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from bioage.biomarkers.parsers.common import parse_double, parse_timestamp
from bioage.biomarkers.parsers.daily import ParsedPoint


def _offset_seconds(raw: object) -> float:
    """Parse a `"7200s"`-style Duration string; 0.0 (UTC) for anything else."""
    if isinstance(raw, str) and raw.endswith("s"):
        try:
            return float(raw[:-1])
        except ValueError:
            return 0.0
    return 0.0


def _minutes_past_midnight(moment: datetime) -> float:
    return moment.hour * 60.0 + moment.minute + moment.second / 60.0


def parse_sleep(payload: dict[str, Any]) -> ParsedPoint | None:
    body = payload.get("sleep")
    if not isinstance(body, dict):
        return None

    metadata = body.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("mainSleep") is not True:
        return None

    interval = body.get("interval")
    if not isinstance(interval, dict) or "startTime" not in interval or "endTime" not in interval:
        return None

    start = parse_timestamp(interval["startTime"])
    end = parse_timestamp(interval["endTime"])
    if (end - start).total_seconds() <= 0:
        return None

    summary = body.get("summary")
    if not isinstance(summary, dict):
        return None

    minutes_asleep = parse_double(summary.get("minutesAsleep"))
    if minutes_asleep is None:
        return None

    start_offset = _offset_seconds(interval.get("startUtcOffset"))
    end_offset = _offset_seconds(interval.get("endUtcOffset", interval.get("startUtcOffset")))

    local_end = end + timedelta(seconds=end_offset)
    utc_midpoint = start + (end - start) / 2
    local_midpoint = utc_midpoint + timedelta(seconds=start_offset)

    values: dict[str, float] = {
        "sleep_total_min": minutes_asleep,
        "sleep_midpoint_local_min": _minutes_past_midnight(local_midpoint),
    }

    minutes_in_period = parse_double(summary.get("minutesInSleepPeriod"))
    if minutes_in_period is not None and minutes_in_period > 0:
        # Clamped to [0, 100]: this flows straight into KDM as a biomarker
        # (bioage.estimators.kdm), where a value outside the physically valid range
        # would skew the estimate rather than just looking wrong in a UI.
        efficiency = minutes_asleep / minutes_in_period * 100.0
        values["sleep_efficiency_pct"] = min(max(efficiency, 0.0), 100.0)

    minutes_awake = parse_double(summary.get("minutesAwake"))
    if minutes_awake is not None:
        values["waso_min"] = minutes_awake

    if metadata.get("stagesStatus") == "SUCCEEDED" and minutes_asleep > 0:
        stage_minutes = _stage_minutes(summary.get("stagesSummary"))
        if "DEEP" in stage_minutes:
            values["deep_pct"] = stage_minutes["DEEP"] / minutes_asleep * 100.0
        if "REM" in stage_minutes:
            values["rem_pct"] = stage_minutes["REM"] / minutes_asleep * 100.0

    return ParsedPoint(local_end.date(), values)


def _stage_minutes(stages_summary: object) -> dict[str, float]:
    minutes_by_stage: dict[str, float] = {}
    if not isinstance(stages_summary, list):
        return minutes_by_stage
    for entry in stages_summary:
        if not isinstance(entry, dict):
            continue
        stage_type = entry.get("type")
        minutes = parse_double(entry.get("minutes"))
        if isinstance(stage_type, str) and minutes is not None:
            minutes_by_stage[stage_type] = minutes_by_stage.get(stage_type, 0.0) + minutes
    return minutes_by_stage
