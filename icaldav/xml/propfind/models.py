"""WebDAV PROPFIND data models and response item representations.

RFC Reference:
    - RFC 4918 Section 14.22: DAV:propstat Element.
    - RFC 4918 Section 14.24: DAV:response Element.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

from icaldav.store.types import ResourceKind, ResourcePath, ResourceTarget


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
