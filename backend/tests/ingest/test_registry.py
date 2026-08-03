import pytest

from bioage.ingest.registry import DATA_TYPES, SCOPES, get_spec

METRICS_SCOPE = "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly"
ACTIVITY_SCOPE = "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly"
SLEEP_SCOPE = "https://www.googleapis.com/auth/googlehealth.sleep.readonly"


@pytest.mark.parametrize(
    "data_type",
    ["daily-resting-heart-rate", "daily-heart-rate-variability", "sleep",
     "daily-respiratory-rate", "daily-oxygen-saturation", "steps",
     "active-zone-minutes", "weight", "height", "daily-vo2-max"],
)
def test_steps_is_capped_at_ninety_days_like_the_others(data_type):
    """Google's documented 14-day cap applies only to calories-in-heart-rate-zone,
    heart-rate, active-minutes and total-calories -- none of which are registered here.
    Every data type in this registry, including steps, uses the 90-day cap.
    """
    assert get_spec(data_type).max_window_days == 90


def test_sleep_uses_the_documented_page_size_of_twenty_five():
    assert get_spec("sleep").page_size == 25


def test_every_spec_has_a_parser_and_a_scope():
    for spec in DATA_TYPES:
        assert callable(spec.parser)
        assert spec.scope.startswith("https://www.googleapis.com/auth/googlehealth.")


EXPECTED_PARSER_NAMES = {
    "daily-resting-heart-rate": "parse_daily_resting_heart_rate",
    "daily-heart-rate-variability": "parse_daily_heart_rate_variability",
    "daily-respiratory-rate": "parse_daily_respiratory_rate",
    "daily-oxygen-saturation": "parse_daily_oxygen_saturation",
    "daily-sleep-temperature-derivations": "parse_daily_sleep_temperature_derivations",
    "steps": "parse_steps",
    "active-zone-minutes": "parse_active_zone_minutes",
    "sleep": "parse_sleep",
    "weight": "parse_weight",
    "height": "parse_height",
    "daily-vo2-max": "_noop",
}


def test_each_spec_is_wired_to_its_own_parser():
    """callable(spec.parser) alone would pass even if two types' parsers were swapped
    (e.g. steps wired to parse_active_zone_minutes); check the wiring is correct too.
    """
    for spec in DATA_TYPES:
        assert spec.parser.__name__ == EXPECTED_PARSER_NAMES[spec.data_type_id]


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
