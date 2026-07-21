"""PROPFIND XML request generation and Multi-Status XML response parsing.

WebDAV XML Concepts Overview:
  - Resource (href): A target URL path representing a calendar collection or individual event file.
  - Property (prop): Metadata key-value attributes stored on a resource (e.g. `DAV:getetag`
    for version checksums, `DAV:displayname` for titles, or `DAV:resourcetype` for collection flags).
  - Property Status (propstat): WebDAV groups properties by their HTTP status code. For example,
    properties successfully retrieved are grouped under an `HTTP/1.1 200 OK` propstat block, while
    unsupported properties are grouped under an `HTTP/1.1 404 Not Found` propstat block.
  - Response (response): Represents one resource (URL) and its associated propstat blocks.
  - Multi-Status (multistatus): The top-level WebDAV XML response container (HTTP status 207)
    containing multiple response elements returned from a PROPFIND collection search.

RFC References:
  - RFC 4918 Section 9.1: PROPFIND Method.
  - RFC 4918 Section 13: DAV:multistatus Response Schema.
  - RFC 4918 Section 14: WebDAV XML Element Definitions.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
import logging
from typing import Any
import xml.etree.ElementTree as ET

from icaldav.xml.namespaces import (
    CALDAV,
    DAV,
    CalDavProp,
    DavProp,
    qname,
    strip_ns,
)

_LOGGER = logging.getLogger(__name__)


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


def build_propfind_xml(props: Sequence[str] | None = None) -> bytes:
    """Build a <d:propfind> XML request body bytes.

    RFC Reference:
        - RFC 4918 Section 9.1: PROPFIND Method.
        - RFC 4918 Section 14.20: DAV:propfind Element.

    Args:
        props: Sequence of property names to request (e.g., ["resourcetype", "getetag", "displayname"]).
            If None or empty, generates an empty <d:propfind/> or <d:allprop/> request.

    Returns:
        Encoded UTF-8 XML byte string.
    """
    root = ET.Element(qname(DAV, "propfind"))

    if not props:
        ET.SubElement(root, qname(DAV, "allprop"))
    else:
        prop_elem = ET.SubElement(root, qname(DAV, "prop"))
        for prop_name in props:
            # Support both short names ("getetag") and namespace-qualified names
            if prop_name.startswith("{"):
                prop_elem.append(ET.Element(prop_name))
            else:
                ET.SubElement(prop_elem, qname(DAV, prop_name))

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def parse_propfind_request(xml_bytes: bytes) -> list[tuple[str, str]] | None:
    """Parse a <DAV:propfind> XML request body to extract requested property names.

    RFC Reference:
        - RFC 4918 Section 9.1: PROPFIND Method.
        - RFC 4918 Section 14.20: DAV:propfind Element.

    Args:
        xml_bytes: Raw XML request byte payload.

    Returns:
        A list of (namespace, local_tag) tuples if explicit properties were requested in <DAV:prop>,
        or None if <DAV:allprop/>, <DAV:propname/>, or no body was supplied.
    """
    if not xml_bytes or not xml_bytes.strip():
        return None

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        _LOGGER.debug("Failed to parse PROPFIND request XML", exc_info=True)
        return None

    if strip_ns(root.tag) != "propfind":
        return None

    for child in root:
        if strip_ns(child.tag) == "prop":
            props: list[tuple[str, str]] = []
            for prop in child:
                tag = prop.tag
                if tag.startswith("{") and "}" in tag:
                    ns_part, local_tag = tag[1:].split("}", 1)
                    props.append((ns_part, local_tag))
                else:
                    props.append((DAV, tag))
            return props

    return None


def parse_multistatus_xml(xml_bytes: bytes) -> list[PropfindItem]:
    """Parse a WebDAV <DAV:multistatus> XML response body into Python dataclasses.

    Parsing Process & Concepts:
      1. WebDAV XML Parsing: Reads the raw XML byte stream returned by a server in response to a
         PROPFIND query (HTTP 207 Multi-Status).
      2. Resource Iteration: Iterates through each `<response>` node in the `<multistatus>` tree,
         where each `<response>` represents a single target resource (collection folder or event file).
      3. Property Status Extraction: Extracts the resource URI (`href`) and parses `<propstat>` blocks.
         Properties grouped by HTTP status (e.g. 200 OK) are parsed into a dictionary:
           - Identifies collection & calendar types inside `<resourcetype>` (`is_collection`, `is_calendar`).
           - Extracts version ETags from `<getetag>`.
           - Extracts display titles from `<displayname>` or custom properties.
      4. Namespace Agnosticism: Uses `strip_ns()` on every element tag to guarantee compatibility
         regardless of server namespace prefix aliases (`d:`, `D:`, `ns0:`).

    RFC Reference:
        - RFC 4918 Section 13: Multi-Status Response.
        - RFC 4918 Section 14.16: DAV:getetag.

    Args:
        xml_bytes: Raw XML response byte payload.

    Returns:
        List of PropfindItem objects representing parsed resources and property status blocks.
    """
    if not xml_bytes or not xml_bytes.strip():
        return []

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        _LOGGER.debug("Failed to parse XML response", exc_info=True)
        return []
    items: list[PropfindItem] = []

    for resp_elem in root:
        if strip_ns(resp_elem.tag) != "response":
            continue

        href = ""
        propstats: list[Propstat] = []

        for child in resp_elem:
            tag_name = strip_ns(child.tag)
            if tag_name == "href" and child.text:
                href = child.text.strip()
            elif tag_name == "propstat":
                status_code = 200
                parsed_props: dict[str, Any] = {}

                for ps_child in child:
                    ps_tag = strip_ns(ps_child.tag)
                    if ps_tag == "status" and ps_child.text:
                        # e.g., "HTTP/1.1 200 OK"
                        status_parts = ps_child.text.strip().split()
                        if len(status_parts) >= 2 and status_parts[1].isdigit():
                            status_code = int(status_parts[1])
                    elif ps_tag == "prop":
                        for prop in ps_child:
                            prop_name = strip_ns(prop.tag)
                            if prop_name == "resourcetype":
                                for rt_child in prop:
                                    rt_tag = strip_ns(rt_child.tag)
                                    if rt_tag == "collection":
                                        parsed_props["is_collection"] = True
                                    elif rt_tag == "calendar" or (
                                        rt_child.tag.startswith(f"{{{CALDAV}}}")
                                        and rt_tag == "calendar"
                                    ):
                                        parsed_props["is_calendar"] = True
                            elif prop_name == "getetag" and prop.text:
                                parsed_props["getetag"] = prop.text.strip()
                            elif prop_name == "displayname" and prop.text:
                                parsed_props["displayname"] = prop.text.strip()
                            else:
                                parsed_props[prop_name] = (
                                    prop.text.strip() if prop.text else ""
                                )

                propstats.append(
                    Propstat(status_code=status_code, properties=parsed_props)
                )

        if href:
            items.append(PropfindItem(href=href, propstats=propstats))

    return items


def create_property_element(
    ns: str,
    tag: str,
    href: str,
    is_collection: bool,
    etag: str | None = None,
) -> ET.Element | None:
    """Construct an XML property Element if supported, or return None if unsupported.

    RFC References:
        - RFC 4918 Section 14.24: DAV:resourcetype and DAV:displayname.
        - RFC 4918 Section 14.19: DAV:getetag.
        - RFC 5397 Section 3: DAV:current-user-principal.
        - RFC 4791 Section 6.2.1: CALDAV:calendar-home-set.
    """
    if ns == DAV and tag == DavProp.RESOURCETYPE:
        rt = ET.Element(qname(DAV, DavProp.RESOURCETYPE))
        if is_collection:
            ET.SubElement(rt, qname(DAV, "collection"))
            ET.SubElement(rt, qname(CALDAV, "calendar"))
        return rt

    if ns == DAV and tag == DavProp.GETETAG:
        if etag:
            etag_elem = ET.Element(qname(DAV, DavProp.GETETAG))
            clean_etag = etag.strip('"')
            etag_elem.text = f'"{clean_etag}"'
            return etag_elem
        return None

    if ns == DAV and tag == DavProp.CURRENT_USER_PRINCIPAL:
        cup = ET.Element(qname(DAV, DavProp.CURRENT_USER_PRINCIPAL))
        href_elem = ET.SubElement(cup, qname(DAV, "href"))
        href_elem.text = "/principals/user/"
        return cup

    if ns == CALDAV and tag == CalDavProp.CALENDAR_HOME_SET:
        chs = ET.Element(qname(CALDAV, CalDavProp.CALENDAR_HOME_SET))
        href_elem = ET.SubElement(chs, qname(DAV, "href"))
        href_elem.text = "/"
        return chs

    if ns == DAV and tag == DavProp.DISPLAYNAME:
        dn = ET.Element(qname(DAV, DavProp.DISPLAYNAME))
        dn.text = href.strip("/").split("/")[-1] or "Calendar"
        return dn

    return None


def append_propfind_response(
    root: ET.Element,
    href: str,
    is_collection: bool,
    etag: str | None = None,
    requested_props: list[tuple[str, str]] | None = None,
) -> None:
    """Append a single <DAV:response> element to a <DAV:multistatus> root XML element.

    RFC References:
        - RFC 4918 Section 9.1 & 14.22: 200 OK and 404 Not Found propstat status groups.
        - RFC 5397 Section 3: DAV:current-user-principal.
        - RFC 4791 Section 6.2.1: CALDAV:calendar-home-set.
    """
    resp = ET.SubElement(root, qname(DAV, "response"))
    href_elem = ET.SubElement(resp, qname(DAV, "href"))
    href_elem.text = href

    if requested_props is None:
        default_props = [
            (DAV, DavProp.RESOURCETYPE),
            (DAV, DavProp.CURRENT_USER_PRINCIPAL),
            (CALDAV, CalDavProp.CALENDAR_HOME_SET),
        ]
        if etag:
            default_props.append((DAV, DavProp.GETETAG))

        propstat = ET.SubElement(resp, qname(DAV, "propstat"))
        prop = ET.SubElement(propstat, qname(DAV, "prop"))
        for ns, tag in default_props:
            elem = create_property_element(ns, tag, href, is_collection, etag)
            if elem is not None:
                prop.append(elem)

        status = ET.SubElement(propstat, qname(DAV, "status"))
        status.text = "HTTP/1.1 200 OK"
    else:
        supported_elems: list[ET.Element] = []
        unsupported_elems: list[ET.Element] = []

        for ns, tag in requested_props:
            elem = create_property_element(ns, tag, href, is_collection, etag)
            if elem is not None:
                supported_elems.append(elem)
            else:
                unsupported_elems.append(ET.Element(qname(ns, tag)))

        if supported_elems:
            propstat_200 = ET.SubElement(resp, qname(DAV, "propstat"))
            prop_200 = ET.SubElement(propstat_200, qname(DAV, "prop"))
            for elem in supported_elems:
                prop_200.append(elem)
            status_200 = ET.SubElement(propstat_200, qname(DAV, "status"))
            status_200.text = "HTTP/1.1 200 OK"

        if unsupported_elems:
            propstat_404 = ET.SubElement(resp, qname(DAV, "propstat"))
            prop_404 = ET.SubElement(propstat_404, qname(DAV, "prop"))
            for elem in unsupported_elems:
                prop_404.append(elem)
            status_404 = ET.SubElement(propstat_404, qname(DAV, "status"))
            status_404.text = "HTTP/1.1 404 Not Found"
