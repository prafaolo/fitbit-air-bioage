from datetime import UTC, date, datetime

import pytest

from bioage.biomarkers.parsers.common import (
    parse_double,
    parse_duration_seconds,
    parse_int64,
    parse_proto_date,
    parse_timestamp,
)


def test_proto_date_uses_year_month_day_fields_not_an_iso_string():
    assert parse_proto_date({"year": 2026, "month": 6, "day": 1}) == date(2026, 6, 1)


def test_proto_date_rejects_missing_fields():
    with pytest.raises(ValueError, match="incomplete proto Date"):
        parse_proto_date({"year": 2026, "month": 6})


def test_duration_parses_the_trailing_s_suffix():
    assert parse_duration_seconds("28800s") == 28800.0


def test_duration_parses_fractional_seconds():
    assert parse_duration_seconds("1.500s") == pytest.approx(1.5)


def test_duration_rejects_a_missing_suffix():
    with pytest.raises(ValueError, match="duration must end with 's'"):
        parse_duration_seconds("28800")


def test_int64_accepts_the_string_encoding_the_api_actually_sends():
    assert parse_int64("12345") == 12345


def test_int64_also_accepts_a_real_integer():
    assert parse_int64(9000) == 9000


def test_int64_passes_none_through():
    assert parse_int64(None) is None


def test_int64_rejects_float_to_prevent_truncation():
    with pytest.raises(ValueError, match="int64 does not accept float"):
        parse_int64(58.5)


def test_int64_rejects_bool_true():
    with pytest.raises(ValueError, match="int64 does not accept bool"):
        parse_int64(True)


def test_int64_rejects_bool_false():
    with pytest.raises(ValueError, match="int64 does not accept bool"):
        parse_int64(False)


def test_double_accepts_number_and_string():
    assert parse_double(58.5) == pytest.approx(58.5)
    assert parse_double("58.5") == pytest.approx(58.5)
    assert parse_double(None) is None


def test_timestamp_is_always_timezone_aware():
    parsed = parse_timestamp("2026-06-01T23:14:00Z")
    assert parsed == datetime(2026, 6, 1, 23, 14, tzinfo=UTC)
    assert parsed.tzinfo is not None


def test_timestamp_accepts_explicit_offsets():
    parsed = parse_timestamp("2026-06-01T23:14:00+02:00")
    assert parsed.utcoffset().total_seconds() == 7200
