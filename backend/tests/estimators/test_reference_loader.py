import pytest
from pydantic import ValidationError

from bioage.reference.loader import Cited, get_ntnu, load_yaml
from bioage.types import Sex


def test_cited_requires_a_source():
    with pytest.raises(ValidationError):
        Cited()


def test_cited_accepts_source_and_defaults_derived_to_false():
    c = Cited(source="Nes et al. 2011")
    assert c.source == "Nes et al. 2011"
    assert c.derived is False


def test_load_yaml_reads_a_reference_file():
    data = load_yaml("ntnu")
    assert "coefficients" in data


def test_ntnu_male_coefficients_match_the_published_equation():
    coeff = get_ntnu().coefficients[Sex.MALE]
    assert coeff.intercept == pytest.approx(100.27)
    assert coeff.age == pytest.approx(-0.296)
    assert coeff.physical_activity == pytest.approx(0.226)
    assert coeff.waist == pytest.approx(-0.369)
    assert coeff.resting_hr == pytest.approx(-0.155)


def test_ntnu_female_coefficients_match_the_published_equation():
    coeff = get_ntnu().coefficients[Sex.FEMALE]
    assert coeff.intercept == pytest.approx(74.74)
    assert coeff.age == pytest.approx(-0.247)
    assert coeff.physical_activity == pytest.approx(0.198)
    assert coeff.waist == pytest.approx(-0.259)
    assert coeff.resting_hr == pytest.approx(-0.114)


def test_ntnu_constants_carry_a_citation():
    assert "Nes" in get_ntnu().source


def test_reference_population_defined_for_both_sexes():
    ref = get_ntnu().reference_population
    assert set(ref) == {Sex.MALE, Sex.FEMALE}
    assert ref[Sex.MALE].waist_cm > 0
