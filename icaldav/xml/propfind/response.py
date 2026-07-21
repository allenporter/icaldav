"""WebDAV PROPFIND XML response building and parsing.

RFC Reference:
    - RFC 4918 Section 9.1: PROPFIND Method.
    - RFC 4918 Section 13: DAV:multistatus Response Schema.
    - RFC 4918 Section 14: WebDAV XML Element Definitions.
"""

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
from icaldav.xml.propfind.models import PropfindItem, Propstat

_LOGGER = logging.getLogger(__name__)


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


def parse_multistatus_xml(xml_bytes: bytes) -> list[PropfindItem]:
    """Parse a WebDAV <DAV:multistatus> XML response body into Python dataclasses.

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
