"""Intermediate Representation (IR) domain models for WebDAV/CalDAV operations.

RFC References:
    - RFC 4918: WebDAV Core
    - RFC 4791: CalDAV Core
    - RFC 6578: Collection Synchronization
"""

from dataclasses import dataclass, field
from typing import Any

from icaldav.filter import CompFilter, TimeRange
from icaldav.store.types import ReportResource


@dataclass(frozen=True)
class PropertyTag:
    """Represents a namespace-qualified WebDAV/CalDAV property tag name.

    Attributes:
        namespace: The XML namespace URI (e.g. "DAV:" or "urn:ietf:params:xml:ns:caldav").
        name: The local element tag name (e.g. "getetag", "calendar-data").
    """

    namespace: str
    name: str

    @property
    def clark_name(self) -> str:
        """Return the Clark notation representation '{namespace}name'."""
        return f"{{{self.namespace}}}{self.name}"


@dataclass(frozen=True)
class PropfindQuery:
    """Parsed, transport-agnostic representation of a PROPFIND request.

    RFC Reference:
        - RFC 4918 Section 9.1: PROPFIND Method.
    """

    href: str
    depth: int
    requested_props: list[PropertyTag] | None
    user_id: str | None


@dataclass(frozen=True)
class SyncCollectionQuery:
    """Parsed, transport-agnostic representation of a sync-collection REPORT query.

    RFC Reference:
        - RFC 6578 Section 3: sync-collection REPORT.
    """

    sync_token: str
    limit: int | None = None


@dataclass(frozen=True)
class CalendarQuery:
    """Parsed, transport-agnostic representation of a calendar-query REPORT request.

    RFC Reference:
        - RFC 4791 Section 7.8: calendar-query REPORT.
    """

    comp_filter: CompFilter
    time_range: TimeRange | None = None
    props: list[PropertyTag] = field(default_factory=list)


@dataclass(frozen=True)
class CalendarMultigetQuery:
    """Parsed, transport-agnostic representation of a calendar-multiget REPORT request.

    RFC Reference:
        - RFC 4791 Section 7.9: calendar-multiget REPORT.
    """

    hrefs: list[str]
    props: list[PropertyTag] = field(default_factory=list)


@dataclass(frozen=True)
class SearchCriteria:
    """Search criterion mapping a property tag name to a match term."""

    prop_tag: str
    match: str


@dataclass(frozen=True)
class PrincipalSearchQuery:
    """Parsed, transport-agnostic representation of a principal-property-search REPORT.

    RFC Reference:
        - RFC 3744 Section 9.4: principal-property-search REPORT.
    """

    criteria: list[SearchCriteria]
    props: list[PropertyTag]
    user_id: str | None = None


@dataclass(frozen=True)
class PropstatBlock:
    """Domain model capturing a single WebDAV property status group.

    RFC Reference:
        - RFC 4918 Section 14.22: DAV:propstat Element.
    """

    status_code: int
    properties: dict[PropertyTag, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WebDavResourceStatus:
    """Domain model representing a single resource status response block.

    RFC Reference:
        - RFC 4918 Section 14.24: DAV:response Element.
    """

    href: str
    propstats: list[PropstatBlock] = field(default_factory=list)


@dataclass(frozen=True)
class WebDavMultiStatus:
    """Domain model capturing a complete multi-resource status response.

    RFC Reference:
        - RFC 4918 Section 13: Multi-Status Response.
    """

    responses: list[WebDavResourceStatus] = field(default_factory=list)


@dataclass(frozen=True)
class ReportMultiStatus:
    """Domain model representing the result of a REPORT query execution."""

    responses: list[ReportResource] = field(default_factory=list)
    missing_hrefs: list[str] = field(default_factory=list)
    deleted_hrefs: list[str] = field(default_factory=list)
    sync_token: str | None = None
    has_more: bool = False
