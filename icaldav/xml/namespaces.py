"""XML Namespace constants and Clark notation utilities.

XML Namespaces & Clark Notation in WebDAV/CalDAV:
  1. XML Namespaces (`DAV:`, `urn:ietf:params:xml:ns:caldav`):
     WebDAV and CalDAV server responses contain XML tags defined by different IETF specifications.
     Namespaces assign a globally unique URI to tag names so that standard WebDAV tags
     (like `DAV:displayname`) are distinguished from CalDAV-specific tags (like `caldav:calendar-data`).

  2. Clark Notation (`{ns}tag`):
     Real-world CalDAV servers (Nextcloud, Apple iCloud, Baïkal, Radicale) use arbitrary prefix aliases
     in their XML payloads. For example:
       - Nextcloud sends: `<d:href xmlns:d="DAV:">`
       - Radicale sends: `<DAV:href xmlns:DAV="DAV:">`
       - Apple iCloud sends: `<n0:href xmlns:n0="DAV:">`
     By converting tag lookups to Clark notation (`qname("DAV:", "href") -> "{DAV:}href"`),
     `icaldav` identifies elements strictly by `{namespace_uri}local_tag`, making element matching
     100% namespace-prefix-agnostic and compatible with all server implementations.

RFC References:
  - RFC 4918 Section 14: WebDAV XML Element Definitions (Namespace: DAV:).
  - RFC 4791 Section 3: CalDAV XML Namespaces (Namespace: urn:ietf:params:xml:ns:caldav).
"""

from enum import StrEnum
import xml.etree.ElementTree as ET

DAV = "DAV:"
CALDAV = "urn:ietf:params:xml:ns:caldav"

ET.register_namespace("d", DAV)
ET.register_namespace("c", CALDAV)


class DavProp(StrEnum):
    """Standard WebDAV property local tag names (RFC 4918, RFC 5397, RFC 3744)."""

    RESOURCETYPE = "resourcetype"
    GETETAG = "getetag"
    DISPLAYNAME = "displayname"
    CURRENT_USER_PRINCIPAL = "current-user-principal"
    PRINCIPAL_URL = "principal-URL"


class CalDavProp(StrEnum):
    """Standard CalDAV property local tag names (RFC 4791)."""

    CALENDAR_HOME_SET = "calendar-home-set"
    CALENDAR_DATA = "calendar-data"
    CALENDAR_USER_ADDRESS_SET = "calendar-user-address-set"


def qname(ns: str, tag: str) -> str:
    """Construct a Clark notation namespace-qualified tag name.

    Clark Notation represents qualified XML element names in the format `{namespace_uri}local_name`.
    This notation is used natively by Python's `xml.etree.ElementTree`.

    Args:
        ns: XML namespace URI string (e.g. "DAV:" or "urn:ietf:params:xml:ns:caldav").
        tag: Local XML element tag name (e.g. "href" or "getetag").

    Returns:
        The Clark notation string, e.g., "{DAV:}href".
    """
    return f"{{{ns}}}{tag}"


def strip_ns(tag: str) -> str:
    """Strip Clark notation namespace prefix from an ElementTree tag name.

    Args:
        tag: An ElementTree element tag string (e.g. "{DAV:}href" or "href").

    Returns:
        The local tag string without namespace, e.g. "href".
    """
    if tag.startswith("{") and "}" in tag:
        return tag.split("}", 1)[1]
    return tag
