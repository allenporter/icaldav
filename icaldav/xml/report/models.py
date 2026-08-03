"""CalDAV REPORT data models.

RFC Reference:
    - RFC 4791 Section 7.8: CALDAV:calendar-query REPORT.
    - RFC 4791 Section 7.9: CALDAV:calendar-multiget REPORT.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
import re


from icaldav.filter import CompFilter
from icaldav.store.types import ResourcePath


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

    @cached_property
    def normalized_etag(self) -> str:
        """Return the entity tag stripped of surrounding quotes."""
        return self.etag.strip('"')

    @cached_property
    def resource_path(self) -> ResourcePath:
        """Return the strongly-typed ResourcePath object for this resource."""
        return ResourcePath.parse(self.href)

    @cached_property
    def normalized_href(self) -> str:
        """Return the canonical normalized URI href string for this resource."""
        return self.resource_path.canonical

    @cached_property
    def extracted_uid(self) -> str | None:
        """Extract iCalendar UID from raw ics_data using regex."""
        if not self.ics_data:
            return None
        match_obj = re.search(
            r"^UID:(.+)$", self.ics_data, re.MULTILINE | re.IGNORECASE
        )
        return match_obj.group(1).strip() if match_obj else None


@dataclass
class PrincipalSearchCriterion:
    """A search criterion inside a <DAV:principal-property-search> REPORT (RFC 3744 §9.4)."""

    prop_tag: str
    match: str


@dataclass
class PrincipalPropertySearchRequest:
    """Parsed representation of a <DAV:principal-property-search> REPORT request (RFC 3744 §9.4)."""

    criteria: list[PrincipalSearchCriterion]


@dataclass
class SyncCollectionRequest:
    """Parsed representation of a <DAV:sync-collection> REPORT request (RFC 6578 §3).

    Attributes:
        sync_token: Synchronization token URI indicating the baseline state.
        sync_level: Depth level string ("1" or "infinite").
        limit: Optional maximum number of results requested by client via <DAV:limit><DAV:nresults>.
    """

    sync_token: str
    sync_level: str = "1"
    limit: int | None = None
