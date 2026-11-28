from datetime import datetime, timedelta, timezone

import pytest

from timeparse import parse_period

# Saturday 28 November 2026, 14:30, Malaysia time (UTC+8).
MYT = timezone(timedelta(hours=8))
NOW = datetime(2026, 11, 28, 14, 30, tzinfo=MYT)


def at(day: int, hour: int = 0, minute: int = 0, month: int = 11) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=MYT)


def rng(q: str):
    p = parse_period(q, NOW)
    return (p.start, p.end) if p else None


@pytest.mark.parametrize("q,expected", [
    ("what did I do today?", (at(28), NOW)),
    ("how long was I in Chrome so far", (at(28), NOW)),
    ("what did I work on yesterday?", (at(27), at(28))),
    ("Yesterday's meeting notes", (at(27), at(28))),
    ("the day before yesterday", (at(26), at(27))),
    ("what was I reading this morning", (at(28, 5), at(28, 12))),
    ("this afternoon", (at(28, 12), at(28, 18))),
    ("what did I do tonight", (at(28, 18), at(29))),
    ("what did I do last night?", (at(27, 18), at(28, 6))),
    ("yesterday evening", (at(27, 18), at(28))),
    ("yesterday morning", (at(27, 5), at(27, 12))),
])
def test_named_days_and_parts_of_day(q, expected):
    assert rng(q) == expected


@pytest.mark.parametrize("q,expected", [
    ("what did I do on Tuesday", (at(24), at(25))),
    ("last tuesday", (at(24), at(25))),
    ("on Saturday", (at(21), at(22))),        # today is Saturday: means last Saturday
    ("this Saturday", (at(28), NOW)),         # ...unless "this Saturday"
    ("on Friday", (at(27), at(28))),
    ("on Monday", (at(23), at(24))),
    ("Sunday", (at(22), at(23))),
])
def test_weekday_names(q, expected):
    assert rng(q) == expected


@pytest.mark.parametrize("q,expected", [
    ("on the 25th", (at(25), at(26))),
    ("on the 30th", (at(30, month=10), at(31, month=10))),   # 30 November is in the future
    ("November 25", (at(25), at(26))),
    ("25 Nov", (at(25), at(26))),
    ("on 3rd of november", (at(3), at(4))),
    ("dec 25", (datetime(2025, 12, 25, tzinfo=MYT), datetime(2025, 12, 26, tzinfo=MYT))),  # last year
])
def test_dates(q, expected):
    assert rng(q) == expected


def test_relative_spans():
    assert rng("in the last 2 hours") == (NOW - timedelta(hours=2), NOW)
    assert rng("past three days") == (NOW - timedelta(days=3), NOW)
    assert rng("over the last week") == (NOW - timedelta(weeks=1), NOW)
    assert rng("last 30 minutes") == (NOW - timedelta(minutes=30), NOW)
    start, end = rng("what was I doing 2 hours ago")
    assert start < NOW - timedelta(hours=2) < end <= NOW
    assert rng("3 days ago") == (at(25), at(26))


def test_weeks_and_months():
    assert rng("last week") == (at(16), at(23))   # calendar week, Monday to Monday
    assert rng("this week") == (at(23), NOW)
    assert rng("last month") == (at(1, month=10), at(1))
    assert rng("this month") == (at(1), NOW)


def test_clock_times():
    assert rng("between 2 and 4pm") == (at(28, 14), at(28, 16))
    assert rng("between 9am and 11:30am") == (at(28, 9), at(28, 11, 30))
    assert rng("since 10am") == (at(28, 10), NOW)
    start, end = rng("what was I looking at around 10am")
    assert start == at(28, 9, 15) and end == at(28, 10, 45)
    # A clock time later than now refers to yesterday.
    start, _ = rng("at 9pm")
    assert start.day == 27


@pytest.mark.parametrize("q", [
    "what was that EEG article about?",
    "who is Paolo Mignone",
    "summarise the seizure detection notes",
    "",
])
def test_no_period(q):
    assert parse_period(q, NOW) is None


def test_period_labels_and_utc():
    p = parse_period("on Tuesday", NOW)
    assert p.label == "Tuesday 24 November"
    start, end = p.as_utc_iso()
    assert start == "2026-11-23T16:00:00+00:00" and end == "2026-11-24T16:00:00+00:00"


def test_respects_the_time_zone():
    utc_now = datetime(2026, 11, 28, 1, 0, tzinfo=timezone.utc)  # 09:00 in Malaysia
    p = parse_period("yesterday", utc_now.astimezone(MYT))
    assert p.start == at(27)
    p_utc = parse_period("yesterday", utc_now)
    assert p_utc.start == datetime(2026, 11, 27, tzinfo=timezone.utc)
