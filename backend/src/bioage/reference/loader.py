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


class PaIndexConstants(Cited):
    steps_knots: list[tuple[float, float]]
    azm_knots: list[tuple[float, float]]
    index_ceiling: float
    fallback_index: float
    fitness_age_sigma_years: float


@lru_cache
def get_pa_index() -> PaIndexConstants:
    return PaIndexConstants(**load_yaml("pa_index"))
