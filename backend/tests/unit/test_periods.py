from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from meterly.billing.periods import Interval, Period, add_months, period_containing


@pytest.mark.parametrize(
    ("anchor", "months", "expected"),
    [
        (date(2026, 1, 31), 1, date(2026, 2, 28)),
        (date(2028, 1, 31), 1, date(2028, 2, 29)),
        (date(2026, 1, 31), 2, date(2026, 3, 31)),
        (date(2026, 11, 15), 3, date(2027, 2, 15)),
        (date(2026, 3, 31), -1, date(2026, 2, 28)),
    ],
)
def test_add_months_clamps_to_month_end(anchor: date, months: int, expected: date) -> None:
    assert add_months(anchor, months) == expected


def test_period_returns_to_anchor_day_after_short_month() -> None:
    anchor = date(2026, 1, 31)
    assert period_containing(anchor, Interval.MONTH, date(2026, 3, 5)) == Period(
        date(2026, 2, 28), date(2026, 3, 31)
    )


def test_yearly_period() -> None:
    assert period_containing(date(2024, 2, 29), Interval.YEAR, date(2026, 6, 1)) == Period(
        date(2026, 2, 28), date(2027, 2, 28)
    )


@given(
    st.dates(min_value=date(2000, 1, 1), max_value=date(2090, 12, 31)),
    st.dates(min_value=date(2000, 1, 1), max_value=date(2090, 12, 31)),
    st.sampled_from(list(Interval)),
)
def test_period_always_contains_the_day(anchor: date, day: date, interval: Interval) -> None:
    period = period_containing(anchor, interval, day)
    assert period.contains(day)
    assert period_containing(anchor, interval, period.end).start == period.end


def test_fraction_of() -> None:
    whole = Period(date(2026, 4, 1), date(2026, 5, 1))
    assert Period(date(2026, 4, 16), date(2026, 5, 1)).fraction_of(whole) * 30 == 15
