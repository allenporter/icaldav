"""CalDAV REPORT data models.

RFC Reference:
    - RFC 4791 Section 7.8: CALDAV:calendar-query REPORT.
    - RFC 4791 Section 7.9: CALDAV:calendar-multiget REPORT.
"""

from dataclasses import dataclass
from icaldav.filter import CompFilter


@dataclass
class CalendarQueryRequest:
    """Parsed representation of a <C:calendar-query> REPORT request body (RFC 4791 §7.8).

    Attributes:
        props: List of property local names requested by the client.
        comp_filter: Root component filter tree to evaluate against stored resources.
    """

    props: list[str]
    comp_filter: CompFilter


@dataclass
class CalendarMultigetRequest:
    """Parsed representation of a <C:calendar-multiget> REPORT request body (RFC 4791 §7.9).

    Attributes:
        props: List of property local names requested by the client.
        hrefs: List of resource href paths to retrieve.
    """

    props: list[str]
    hrefs: list[str]


@dataclass
class ReportResource:
    """A single resource entry in a REPORT 207 Multi-Status response.

    Attributes:
        href: Resource URI path.
        etag: Entity tag for version tracking.
        ics_data: Raw iCalendar content, if requested via calendar-data property.
    """

    href: str
    etag: str
    ics_data: str | None = None
