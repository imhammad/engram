"""Find the time period a question is about, in the user's local time.

Deterministic on purpose: "yesterday" must mean the same thing every time,
and dates are where a small language model is least reliable. Returns a
half-open range [start, end) as aware datetimes, or None when the question
names no period.

Understood: today, yesterday, the day before yesterday, tonight, this
morning / afternoon / evening, last night, this week / last week, this
month / last month, weekday names ("on Tuesday", "last Friday"), day of
month ("on the 25th", "November 25", "25 Nov"), "N minutes/hours/days ago",
"in the last N hours/days", "past N days", "since 3pm", "between 2 and 4pm"
(today), and plain times like "at 10am".
"""

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, tzinfo

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]
_MONTH_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                 "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12, "couple": 2, "few": 3}


@dataclass(frozen=True)
class Period:
    start: datetime
    end: datetime
    label: str  # human wording, e.g. "yesterday" or "Tuesday 25 November"

    def as_utc_iso(self) -> tuple[str, str]:
        from datetime import timezone
        return self.start.astimezone(timezone.utc).isoformat(), self.end.astimezone(timezone.utc).isoformat()


def _day(d: datetime) -> datetime:
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


def _span(start: datetime, end: datetime, label: str) -> Period:
    return Period(start, end, label)


def _whole_day(d: datetime, label: str) -> Period:
    s = _day(d)
    return Period(s, s + timedelta(days=1), label)


def _number(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return _NUMBER_WORDS.get(token)


def _parse_clock(hour: str, minute: str | None, ampm: str | None) -> time | None:
    h, m = int(hour), int(minute or 0)
    if ampm:
        ampm = ampm.replace(".", "")
        if h == 12:
            h = 0
        if ampm.startswith("p"):
            h += 12
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return time(h, m)


def _fmt_day(d: datetime) -> str:
    return f"{WEEKDAYS[d.weekday()].capitalize()} {d.day} {MONTHS[d.month - 1].capitalize()}"


def parse_period(question: str, now: datetime) -> Period | None:
    """`now` must be timezone-aware, in the user's local time zone."""
    q = " " + question.lower().replace("’", "'") + " "
    today = _day(now)

    # Relative spans counted back from now.
    m = re.search(r"\b(?:in the |over the |during the )?(?:last|past) (\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|twelve|couple of|few) (minute|hour|day|week)s?\b", q)
    if m:
        n = _number(m.group(1).replace(" of", "")) or 1
        unit = {"minute": timedelta(minutes=1), "hour": timedelta(hours=1), "day": timedelta(days=1), "week": timedelta(weeks=1)}[m.group(2)]
        return _span(now - n * unit, now, f"the last {n} {m.group(2)}{'s' if n != 1 else ''}")
    m = re.search(r"\b(?:(?:in|over|during) the (?:last|past)|past) (minute|hour|day|week)\b", q)
    if m:
        unit = {"minute": timedelta(minutes=1), "hour": timedelta(hours=1), "day": timedelta(days=1), "week": timedelta(weeks=1)}[m.group(1)]
        return _span(now - unit, now, f"the last {m.group(1)}")
    m = re.search(r"\b(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|twelve|couple of|few) (minute|hour|day|week)s? ago\b", q)
    if m:
        n = _number(m.group(1).replace(" of", "")) or 1
        if m.group(2) in ("minute", "hour"):
            unit = timedelta(minutes=1) if m.group(2) == "minute" else timedelta(hours=1)
            centre = now - n * unit
            # "2 hours ago" means around then: a window either side.
            return _span(centre - unit / 2 - timedelta(minutes=15), min(centre + unit / 2 + timedelta(minutes=15), now), f"about {n} {m.group(2)}{'s' if n != 1 else ''} ago")
        if m.group(2) == "day":
            return _whole_day(today - timedelta(days=n), f"{n} day{'s' if n != 1 else ''} ago")
        start = today - timedelta(days=today.weekday()) - timedelta(weeks=n)
        return _span(start, start + timedelta(weeks=1), f"{n} week{'s' if n != 1 else ''} ago")

    # Times of day.
    if re.search(r"\blast night\b", q):
        y = today - timedelta(days=1)
        return _span(y.replace(hour=18), today.replace(hour=6), "last night")
    if re.search(r"\btonight\b|\bthis evening\b", q):
        return _span(today.replace(hour=18), today + timedelta(days=1), "this evening")
    if re.search(r"\bthis morning\b", q):
        return _span(today.replace(hour=5), today.replace(hour=12), "this morning")
    if re.search(r"\bthis afternoon\b", q):
        return _span(today.replace(hour=12), today.replace(hour=18), "this afternoon")
    m = re.search(r"\byesterday (morning|afternoon|evening)\b", q)
    if m:
        y = today - timedelta(days=1)
        hours = {"morning": (5, 12), "afternoon": (12, 18), "evening": (18, 24)}[m.group(1)]
        return _span(y + timedelta(hours=hours[0]), y + timedelta(hours=hours[1]), f"yesterday {m.group(1)}")

    # Clock ranges and anchors, today.
    m = re.search(r"\bbetween (\d{1,2})(?::(\d{2}))? ?(am|pm|a\.m\.|p\.m\.)? and (\d{1,2})(?::(\d{2}))? ?(am|pm|a\.m\.|p\.m\.)?", q)
    if m:
        end_ampm = m.group(6)
        t1 = _parse_clock(m.group(1), m.group(2), m.group(3) or end_ampm)
        t2 = _parse_clock(m.group(4), m.group(5), end_ampm)
        if t1 and t2:
            return _span(datetime.combine(today.date(), t1, now.tzinfo), datetime.combine(today.date(), t2, now.tzinfo),
                         f"today between {t1.strftime('%H:%M')} and {t2.strftime('%H:%M')}")
    m = re.search(r"\bsince (\d{1,2})(?::(\d{2}))? ?(am|pm|a\.m\.|p\.m\.)\b", q)
    if m:
        t = _parse_clock(m.group(1), m.group(2), m.group(3))
        if t:
            return _span(datetime.combine(today.date(), t, now.tzinfo), now, f"since {t.strftime('%H:%M')}")

    # Named days.
    if re.search(r"\bday before yesterday\b", q):
        return _whole_day(today - timedelta(days=2), "the day before yesterday")
    if re.search(r"\byesterday\b", q):
        return _whole_day(today - timedelta(days=1), "yesterday")
    if re.search(r"\btoday\b|\bso far\b", q):
        return _span(today, now, "today")

    # Weeks and months.
    if re.search(r"\blast week\b", q):
        start = today - timedelta(days=today.weekday() + 7)
        return _span(start, start + timedelta(days=7), "last week")
    if re.search(r"\bthis week\b", q):
        return _span(today - timedelta(days=today.weekday()), now, "this week")
    if re.search(r"\blast month\b", q):
        first_this = today.replace(day=1)
        first_last = (first_this - timedelta(days=1)).replace(day=1)
        return _span(first_last, first_this, "last month")
    if re.search(r"\bthis month\b", q):
        return _span(today.replace(day=1), now, "this month")

    # Weekday names: the most recent such day before today ("on Tuesday",
    # "last Tuesday"); "this Tuesday" when it is today means today.
    m = re.search(r"\b(?:on |last |this |past )?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?\b", q)
    if m:
        target = WEEKDAYS.index(m.group(1))
        back = (today.weekday() - target) % 7
        if back == 0 and not re.search(r"\bthis " + m.group(1), q):
            back = 7
        d = today - timedelta(days=back)
        return _whole_day(d, _fmt_day(d)) if d != today else _span(today, now, "today")

    # Dates: "the 25th", "25 November", "November 25", "25/11".
    m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)? (?:of )?{_MONTH_RE}\b", q) or re.search(rf"\b{_MONTH_RE} (\d{{1,2}})(?:st|nd|rd|th)?\b", q)
    if m:
        groups = m.groups()
        day_s, month_s = (groups[0], groups[1]) if groups[0].isdigit() else (groups[1], groups[0])
        month = next(i for i, name in enumerate(MONTHS, 1) if name.startswith(month_s[:3]))
        try:
            d = today.replace(month=month, day=int(day_s))
        except ValueError:
            return None
        if d > today:
            d = d.replace(year=d.year - 1)
        return _whole_day(d, _fmt_day(d))
    m = re.search(r"\b(?:on )?the (\d{1,2})(?:st|nd|rd|th)\b", q)
    if m:
        day_n = int(m.group(1))
        d = today
        for _ in range(2):
            try:
                cand = d.replace(day=day_n)
            except ValueError:
                cand = None
            if cand and cand <= today:
                return _whole_day(cand, _fmt_day(cand))
            d = (d.replace(day=1) - timedelta(days=1))
        return None

    # A plain clock time today: "at 10am", "around 3 pm".
    m = re.search(r"\b(?:at|around) (\d{1,2})(?::(\d{2}))? ?(am|pm|a\.m\.|p\.m\.)\b", q)
    if m:
        t = _parse_clock(m.group(1), m.group(2), m.group(3))
        if t:
            c = datetime.combine(today.date(), t, now.tzinfo)
            if c > now:
                c -= timedelta(days=1)
            return _span(c - timedelta(minutes=45), c + timedelta(minutes=45), f"around {t.strftime('%H:%M')}")
    return None


def local_now(tz: tzinfo | None = None) -> datetime:
    return datetime.now(tz) if tz else datetime.now().astimezone()
