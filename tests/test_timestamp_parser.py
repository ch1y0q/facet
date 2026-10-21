"""The shared date parser and its two emitters (``api.db_helpers``)."""

import pytest

from api.db_helpers import parse_timestamp, to_day_granularity, to_second_granularity

FORMS = ["2025-06-01", "2025-06-01 10:30:15", "2025-06-01T10:30:15", "2025-06-01T10:30",
         "2025:06:01", "2025:06:01 10:30:15"]


@pytest.mark.parametrize("value", FORMS)
def test_every_accepted_form_parses(value):
    moment, _ = parse_timestamp(value)
    assert (moment.year, moment.month, moment.day) == (2025, 6, 1)


@pytest.mark.parametrize("value,expected", [
    ("2025-06-01", "2025:06:01 00:00:00"), ("2025:06:01", "2025:06:01 00:00:00"),
    ("2025-06-01T10:30", "2025:06:01 10:30:00"), ("2025-06-01 10:30:15", "2025:06:01 10:30:15"),
    ("2025:06:01 10:30:15", "2025:06:01 10:30:15")])
def test_second_granularity(value, expected):
    assert to_second_granularity(value) == expected


def test_a_date_only_end_bound_covers_the_whole_day():
    assert to_second_granularity("2025-06-01", end_of_day=True) == "2025:06:01 23:59:59"
    assert to_second_granularity("2025-06-01 08:00:00", end_of_day=True) == "2025:06:01 08:00:00"


@pytest.mark.parametrize("value", ["2025-06-01", "2025:06:01"])
def test_day_granularity_emits_iso(value):
    assert to_day_granularity(value) == "2025-06-01"


@pytest.mark.parametrize("value", ["2025-06-01 10:30:15", "2025-06-01T10:30", "2025:06:01 10:30:15"])
def test_day_granularity_refuses_a_time_and_names_the_form(value):
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        to_day_granularity(value)


@pytest.mark.parametrize("value", ["", "yesterday", "2025-13-01", "2025-02-30", "2025-06-01 25:00:00",
                                   "2025/06/01", "2025-06:01"])
def test_garbage_is_refused_naming_the_accepted_forms(value):
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        parse_timestamp(value)
