from datetime import date

import pytest

from bioage.types import DateRange, Sex


def test_sex_values():
    assert Sex.MALE.value == "male"
    assert Sex.FEMALE.value == "female"


def test_date_range_days_is_inclusive_of_start_exclusive_of_end():
    assert DateRange(date(2026, 1, 1), date(2026, 1, 15)).days == 14


def test_date_range_rejects_end_before_start():
    with pytest.raises(ValueError, match="end must be after start"):
        DateRange(date(2026, 1, 15), date(2026, 1, 1))


def test_chunked_splits_range_into_windows_no_larger_than_max():
    chunks = list(DateRange(date(2026, 1, 1), date(2026, 3, 2)).chunked(14))
    assert all(c.days <= 14 for c in chunks)
    assert chunks[0].start == date(2026, 1, 1)
    assert chunks[-1].end == date(2026, 3, 2)
    # contiguous, no gaps or overlaps
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        assert prev.end == nxt.start


def test_chunked_60_day_steps_backfill_produces_five_requests():
    chunks = list(DateRange(date(2026, 1, 1), date(2026, 3, 2)).chunked(14))
    assert len(chunks) == 5


def test_chunked_returns_single_chunk_when_range_fits():
    chunks = list(DateRange(date(2026, 1, 1), date(2026, 1, 10)).chunked(14))
    assert len(chunks) == 1
    assert chunks[0] == DateRange(date(2026, 1, 1), date(2026, 1, 10))
