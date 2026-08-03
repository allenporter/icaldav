"""WebDAV PROPFIND data models and response item representations.

RFC Reference:
    - RFC 4918 Section 14.22: DAV:propstat Element.
    - RFC 4918 Section 14.24: DAV:response Element.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from functools import cached_property
from typing import Any


from icaldav.store.principal import PrincipalInfo
from icaldav.store.types import ResourcePath


class ResourceKind(StrEnum):
    """Resource entity classification provided directly by handlers (RFC 3744, RFC 4918, RFC 4791)."""

    PRINCIPAL = "principal"
    """WebDAV Principal resource (RFC 3744 §4.1)."""

    ROOT = "root"
    """Root WebDAV collection container (RFC 4918 §14.24)."""

    CALENDAR = "calendar"
    """CalDAV Calendar collection (RFC 4791 §4.2)."""

    RESOURCE = "resource"
    """Individual calendar object resource / file (RFC 4791 §9.6)."""


@dataclass(frozen=True)
class ResourceTarget:
    """Domain model capturing target resource context for WebDAV property responses.

    Attributes:
        href: Canonical relative URI path string (e.g. "/", "/principals/user/", "/work/").
        kind: Explicit ResourceKind classification provided directly by the handler.
        displayname: Optional human-readable display name string.
        etag: Optional entity tag string for cache control.
        ctag: Optional collection change tag string for fast client sync diffing.
        sync_token: Optional synchronization token URI for RFC 6578 WebDAV Sync.
        principal: Optional PrincipalInfo metadata object for WebDAV autodiscovery properties.
    """

    href: str
    kind: ResourceKind
    displayname: str | None = None
    etag: str | None = None
    ctag: str | None = None
    sync_token: str | None = None
    principal: PrincipalInfo | None = None


@dataclass
class Propstat:
    """Represents a <DAV:propstat> element inside a WebDAV Multi-Status response item.

    In WebDAV, properties requested for a resource are grouped by their HTTP status code.
    This class captures a single status group and its parsed properties dictionary.

    RFC Reference:
        - RFC 4918 Section 14.22: DAV:propstat Element.

    Attributes:
        status_code: HTTP integer status code (e.g. 200 OK, 404 Not Found).
        properties: Dictionary mapping property names to parsed values
            (e.g., {"getetag": '"etag-1"', "is_collection": True}).
    """

    status_code: int
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class PropfindItem:
    """Represents a single <DAV:response> element inside a Multi-Status XML response.

    Each PropfindItem corresponds to one resource (file or calendar collection) found
    during a PROPFIND query, holding its relative URI path (`href`) and property status blocks.

    RFC Reference:
        - RFC 4918 Section 14.24: DAV:response Element.

    Attributes:
        href: The relative URI path of the resource or collection.
        propstats: List of Propstat objects describing requested properties grouped by status.
    """

    href: str
    propstats: list[Propstat] = field(default_factory=list)

    @property
    def is_collection(self) -> bool:
        """Helper checking if any 200 propstat identifies this resource as a collection."""
        for ps in self.propstats:
            if ps.status_code == 200 and ps.properties.get("is_collection"):
                return True
        return False

    @property
    def is_calendar(self) -> bool:
        """Helper checking if any 200 propstat identifies this resource as a CalDAV calendar."""
        for ps in self.propstats:
            if ps.status_code == 200 and ps.properties.get("is_calendar"):
                return True
        return False

    @property
    def etag(self) -> str | None:
        """Helper returning the DAV:getetag property value if present in a 200 OK status."""
        for ps in self.propstats:
            if ps.status_code == 200 and "getetag" in ps.properties:
                return ps.properties["getetag"]
        return None

    @cached_property
    def normalized_etag(self) -> str | None:
        """Return the DAV:getetag property value stripped of surrounding quotes."""
        raw = self.etag
        return raw.strip('"') if raw is not None else None

    @cached_property
    def resource_path(self) -> ResourcePath:
        """Return the strongly-typed ResourcePath object for this item."""
        return ResourcePath.parse(self.href)

    @cached_property
    def normalized_href(self) -> str:
        """Return the canonical normalized URI href string for this item."""
        return self.resource_path.canonical
