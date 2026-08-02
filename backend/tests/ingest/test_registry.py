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
