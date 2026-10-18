"""Generic iCalendar content filtering for server-side REPORT evaluation and local search.

Provides functions to evaluate whether raw iCalendar (RFC 5545) content matches
CalDAV filter criteria such as component type and time range. These functions
are used by the CalDAV REPORT handler but are designed to be reusable for
client-side local calendar search and filtering.

Filtering Lifecycle:
  1. A CalDAV client sends a REPORT request with a <C:filter> element.
  2. The server parses the filter into CompFilter/TimeRange dataclasses.
  3. These functions evaluate each stored iCalendar resource against the filter.
  4. Only matching resources are included in the 207 Multi-Status response.

RFC References:
  - RFC 4791 Section 7.8: calendar-query REPORT.
  - RFC 4791 Section 9.7: CALDAV:comp-filter element.
  - RFC 4791 Section 9.9: CALDAV:time-range element.
  - RFC 5545: Internet Calendaring (iCalendar) format.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from ical.calendar import Calendar
from ical.calendar_stream import IcsCalendarStream
from ical.exceptions import CalendarError
from ical.timeline import generic_timeline

_MIN_DT = datetime(1, 1, 1, tzinfo=UTC)
_MAX_DT = datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC)


@dataclass
class TimeRange:
    """Represents a CALDAV:time-range filter element (RFC 4791 §9.9).

    Defines a half-open time interval [start, end) used to filter calendar
    components by temporal overlap. A component matches if its effective
    time boundary overlaps the filter interval.

    Overlap condition per RFC 4791 §9.9:
        (filter_start < component_end) AND (filter_end > component_start)

    Open-ended ranges:
        - If start is None, the interval is (-∞, end)
        - If end is None, the interval is [start, +∞)
        - If both are None, all components match
    """

    start: str | None = None
    """Optional UTC start boundary in iCalendar DATE-TIME format (e.g. '20260701T000000Z').

    When present, only components whose effective end time is after this value
    will match. Corresponds to the 'start' attribute of <C:time-range>.
    RFC 4791 §9.9.
    """

    end: str | None = None
    """Optional UTC end boundary in iCalendar DATE-TIME format (e.g. '20260801T000000Z').

    When present, only components whose effective start time is before this value
    will match. Corresponds to the 'end' attribute of <C:time-range>.
    RFC 4791 §9.9.
    """


@dataclass
class CompFilter:
    """Represents a CALDAV:comp-filter element for matching iCalendar components (RFC 4791 §9.7).

    Component filters form a tree structure mirroring iCalendar component nesting.
    The top-level filter must match 'VCALENDAR', with nested filters for specific
    component types like 'VEVENT', 'VTODO', or 'VJOURNAL'.

    Filter evaluation (RFC 4791 §9.7.1):
        A comp-filter matches a component if:
        1. The component name matches the 'name' attribute (case-insensitive).
        2. If time_range is specified, the component's time boundary overlaps it.
        3. All nested comp_filters match at least one sub-component.

    Example filter tree for 'all VEVENTs in July 2026':
        CompFilter(name='VCALENDAR', comp_filters=[
            CompFilter(name='VEVENT', time_range=TimeRange(
                start='20260701T000000Z', end='20260801T000000Z'
            ))
        ])
    """

    name: str
    """iCalendar component name to match (e.g. 'VCALENDAR', 'VEVENT', 'VTODO', 'VJOURNAL').

    Matched case-insensitively against BEGIN:xxx lines in iCalendar data.
    The top-level comp-filter MUST have name='VCALENDAR' per RFC 4791 §7.8.
    """

    time_range: TimeRange | None = None
    """Optional time range constraint for this component (RFC 4791 §9.9).

    When set, the component must have a time boundary (DTSTART/DTEND or DTSTART/DURATION)
    that overlaps this range. Only meaningful for time-based components (VEVENT, VTODO, VFREEBUSY).
    """

    comp_filters: list["CompFilter"] = field(default_factory=list)
    """Nested component filters that must match sub-components (RFC 4791 §9.7).

    For example, a VCALENDAR comp-filter may contain a VEVENT comp-filter
    to restrict results to calendar objects containing events.
    """


def _parse_filter_dt(value: str | None) -> datetime | None:
    """Parse an iCalendar DATE or DATE-TIME string into a UTC datetime."""
    if not value or not (s := value.strip()):
        return None
    if "T" in s.upper():
        dt = datetime.fromisoformat(s)
        return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    d = date.fromisoformat(s)
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def _matches_sub_filter(calendar: Calendar, sub_filter: CompFilter) -> bool:
    """Evaluate a single child CompFilter against a parsed ical.Calendar."""
    comp_name = sub_filter.name.upper()
    if comp_name == "VEVENT":
        if not calendar.events:
            return False
        if sub_filter.time_range is None:
            return True
        start_dt = _parse_filter_dt(sub_filter.time_range.start) or _MIN_DT
        end_dt = _parse_filter_dt(sub_filter.time_range.end) or _MAX_DT
        return any(calendar.timeline_tz(UTC).overlapping(start_dt, end_dt))
    if comp_name == "VTODO":
        if not calendar.todos:
            return False
        if sub_filter.time_range is None:
            return True
        start_dt = _parse_filter_dt(sub_filter.time_range.start) or _MIN_DT
        end_dt = _parse_filter_dt(sub_filter.time_range.end) or _MAX_DT
        dated_todos = [t for t in calendar.todos if t.dtstart is not None]
        if any(t.dtstart is None for t in calendar.todos):
            return True
        return bool(dated_todos) and any(
            generic_timeline(dated_todos, UTC).overlapping(start_dt, end_dt)
        )
    return False


def matches_comp_filter(ics_data: str, comp_filter: CompFilter) -> bool:
    """Evaluate whether raw iCalendar data matches a comp-filter tree.

    Args:
        ics_data: Raw iCalendar string content.
        comp_filter: The top-level CompFilter to evaluate (usually VCALENDAR).

    Returns:
        True if the data matches the filter tree, False otherwise.
    """
    if comp_filter.name.upper() != "VCALENDAR":
        return False

    try:
        calendar = IcsCalendarStream.calendar_from_ics(ics_data)
        return all(
            _matches_sub_filter(calendar, sub_filter)
            for sub_filter in comp_filter.comp_filters
        )
    except (CalendarError, ValueError):
        return False
