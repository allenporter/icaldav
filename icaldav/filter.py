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


def extract_component_types(ics_data: str) -> list[str]:
    """Extract all top-level component type names (VEVENT, VTODO, etc.) from raw iCalendar data.

    Does NOT parse VCALENDAR itself, only inner components.

    Args:
        ics_data: Raw iCalendar string content.

    Returns:
        List of component type strings like ['VEVENT'] or ['VTODO'].
    """
    types = []
    lines = ics_data.splitlines()
    in_vcalendar = False
    for line in lines:
        line_upper = line.strip().upper()
        if line_upper == "BEGIN:VCALENDAR":
            in_vcalendar = True
            continue
        if line_upper == "END:VCALENDAR":
            break
        if in_vcalendar and line_upper.startswith("BEGIN:"):
            comp_type = line_upper[6:]
            types.append(comp_type)
    return types


def extract_time_range(ics_data: str) -> tuple[str | None, str | None]:
    """Extract DTSTART and DTEND values from raw iCalendar data.

    Args:
        ics_data: Raw iCalendar string content.

    Returns:
        Tuple of (dtstart, dtend) as strings, or None for missing values.
    """
    dtstart = None
    dtend = None
    lines = ics_data.splitlines()
    for line in lines:
        line_upper = line.strip().upper()
        if line_upper.startswith(("DTSTART:", "DTSTART;")):
            parts = line.split(":", 1)
            if len(parts) > 1:
                dtstart = parts[1].strip()
        elif line_upper.startswith(("DTEND:", "DTEND;")):
            parts = line.split(":", 1)
            if len(parts) > 1:
                dtend = parts[1].strip()

    return dtstart, dtend


def time_ranges_overlap(
    event_start: str | None,
    event_end: str | None,
    filter_start: str | None,
    filter_end: str | None,
) -> bool:
    """Check if an event's time range overlaps a filter's time range.

    Uses the half-open interval [start, end) overlap condition from RFC 4791 §9.9:
    (filter_start < component_end) AND (filter_end > component_start)

    Args:
        event_start: Event start time string (or None).
        event_end: Event end time string (or None).
        filter_start: Filter start time string (or None).
        filter_end: Filter end time string (or None).

    Returns:
        True if there is temporal overlap, False otherwise.
    """
    if event_start is None:
        return False

    if event_end is None:
        event_end = event_start

    cond1 = True
    if filter_start is not None:
        cond1 = filter_start < event_end

    cond2 = True
    if filter_end is not None:
        cond2 = filter_end > event_start

    return cond1 and cond2


def matches_comp_filter(ics_data: str, comp_filter: CompFilter) -> bool:
    """Evaluate whether raw iCalendar data matches a comp-filter tree.

    Args:
        ics_data: Raw iCalendar string content.
        comp_filter: The top-level CompFilter to evaluate (usually VCALENDAR).

    Returns:
        True if the data matches the filter tree, False otherwise.
    """
    if comp_filter.name.upper() == "VCALENDAR":
        if not comp_filter.comp_filters:
            return True

        comp_types = extract_component_types(ics_data)

        for sub_filter in comp_filter.comp_filters:
            matched_sub = False

            for ctype in comp_types:
                if ctype.upper() == sub_filter.name.upper():
                    if sub_filter.time_range:
                        ev_start, ev_end = extract_time_range(ics_data)
                        if time_ranges_overlap(
                            ev_start,
                            ev_end,
                            sub_filter.time_range.start,
                            sub_filter.time_range.end,
                        ):
                            matched_sub = True
                            break
                    else:
                        matched_sub = True
                        break

            if not matched_sub:
                return False

        return True

    return False
