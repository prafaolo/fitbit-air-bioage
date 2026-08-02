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
from typing import TypedDict

import numpy as np
import yaml


class _NormSpec(TypedDict):
    source: str
    points: list[tuple[float, float, float]]


NORMS: dict[str, _NormSpec] = {
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
            "Nightly RMSSD normative medians from docs/reference-research-from-claude.md, "
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
        q, k, s = fit(spec["points"])
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
        "biomarkers": biomarkers,
    }

    out = Path(__file__).parent / "kdm_biomarkers.yaml"
    with out.open("w") as handle:
        yaml.safe_dump(document, handle, sort_keys=False, width=88)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
