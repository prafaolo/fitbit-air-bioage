import pytest

from bioage.biomarkers.regularity import sleep_regularity_minutes

MINUTES_PER_DAY = 1440


def test_returns_none_for_too_few_nights():
    assert sleep_regularity_minutes([180.0, 190.0]) is None


def test_identical_midpoints_have_zero_variability():
    assert sleep_regularity_minutes([180.0] * 10) == pytest.approx(0.0, abs=1e-9)


def test_midpoints_straddling_midnight_are_treated_as_close_together():
    """23:50, 00:00 and 00:10 are 20 minutes apart in total, not 1420."""
    straddling = [1430.0, 0.0, 10.0]
    assert sleep_regularity_minutes(straddling) < 30.0


def test_naive_standard_deviation_would_be_wrong_here():
    """Guard against a future 'simplification' to statistics.stdev."""
    import statistics

    straddling = [1430.0, 0.0, 10.0]
    naive = statistics.stdev(straddling)
    circular = sleep_regularity_minutes(straddling)
    assert circular is not None
    assert naive > 500.0
    assert circular < 30.0


def test_more_scattered_midpoints_give_larger_variability():
    tight = sleep_regularity_minutes([180.0, 185.0, 175.0, 182.0, 178.0])
    loose = sleep_regularity_minutes([120.0, 300.0, 60.0, 400.0, 200.0])
    assert tight is not None and loose is not None
    assert tight < loose


def test_result_is_never_negative():
    assert sleep_regularity_minutes([0.0, 720.0, 1439.0]) >= 0.0


def test_maximally_scattered_midpoints_do_not_exceed_a_quarter_day():
    """Circular SD saturates; it must not blow up past a physically meaningful bound."""
    scattered = [i * MINUTES_PER_DAY / 12 for i in range(12)]
    result = sleep_regularity_minutes(scattered)
    assert result is not None
    assert result <= MINUTES_PER_DAY / 2
