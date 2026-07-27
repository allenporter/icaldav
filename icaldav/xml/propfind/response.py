"""WebDAV PROPFIND XML response building and parsing.

RFC Reference:
    - RFC 4918 Section 9.1: PROPFIND Method.
    - RFC 4918 Section 13: DAV:multistatus Response Schema.
    - RFC 4918 Section 14: WebDAV XML Element Definitions.
"""

import logging
from typing import Any
import xml.etree.ElementTree as ET

from icaldav.store.principal import InMemoryPrincipalStore
from icaldav.xml.namespaces import (
    CALDAV,
    CALSERVER,
    DAV,
    DEFAULT_SUPPORTED_COMPONENTS,
    CalDavProp,
    CalServerProp,
    DavProp,
    qname,
    strip_ns,
)
from icaldav.xml.propfind.models import (
    PropfindItem,
    Propstat,
    ResourceKind,
    ResourceTarget,
)

_LOGGER = logging.getLogger(__name__)
_DEFAULT_PRINCIPAL = InMemoryPrincipalStore()._principals["user"]


def _build_href_property(ns: str, tag: str, href_val: str) -> ET.Element:
    """Helper to construct an XML element wrapping a <DAV:href> child element."""
    elem = ET.Element(qname(ns, tag))
    ET.SubElement(elem, qname(DAV, "href")).text = href_val
    return elem


def _build_resourcetype_property(kind: ResourceKind) -> ET.Element:
    """Helper to construct a <DAV:resourcetype> XML element based on ResourceKind."""
    rt = ET.Element(qname(DAV, DavProp.RESOURCETYPE))
    if kind == ResourceKind.PRINCIPAL:
        ET.SubElement(rt, qname(DAV, "collection"))
        ET.SubElement(rt, qname(DAV, DavProp.PRINCIPAL))
    elif kind == ResourceKind.ROOT:
        ET.SubElement(rt, qname(DAV, "collection"))
    elif kind == ResourceKind.CALENDAR:
        ET.SubElement(rt, qname(DAV, "collection"))
        ET.SubElement(rt, qname(CALDAV, "calendar"))
    return rt


def _build_current_user_privilege_set_property() -> ET.Element:
    """Helper constructing <DAV:current-user-privilege-set> for full read/write access. RFC 3744 §5.3."""
    cups = ET.Element(qname(DAV, DavProp.CURRENT_USER_PRIVILEGE_SET))
    priv = ET.SubElement(cups, qname(DAV, "privilege"))
    for p_name in ("read", "write", "write-properties", "write-content", "all"):
        ET.SubElement(priv, qname(DAV, p_name))
    return cups


def _build_supported_report_set_property(kind: ResourceKind) -> ET.Element | None:
    """Helper constructing <DAV:supported-report-set> element. RFC 3253 §3.1.5, RFC 4791 §5.3.1."""
    if kind != ResourceKind.CALENDAR:
        return None
    srs = ET.Element(qname(DAV, DavProp.SUPPORTED_REPORT_SET))
    for r_ns, r_tag in ((CALDAV, "calendar-query"), (CALDAV, "calendar-multiget")):
        sr = ET.SubElement(srs, qname(DAV, "supported-report"))
        rep = ET.SubElement(sr, qname(DAV, "report"))
        ET.SubElement(rep, qname(r_ns, r_tag))
    return srs


def create_property_element(
    ns: str,
    tag: str,
    target: ResourceTarget,
) -> ET.Element | None:
    """Construct an XML property Element if supported, or return None if unsupported.

    RFC References:
        - RFC 4918 Section 14.24: DAV:resourcetype and DAV:displayname.
        - RFC 4918 Section 14.19: DAV:getetag.
        - RFC 5397 Section 3: DAV:current-user-principal.
        - RFC 4791 Section 6.2.1: CALDAV:calendar-home-set.
        - RFC 3744 Section 4.2: DAV:principal-URL.
        - RFC 3744 Section 5.1: DAV:owner.
        - RFC 3744 Section 5.3: DAV:current-user-privilege-set.
        - RFC 3253 Section 3.1.5: DAV:supported-report-set.
        - RFC 4791 Section 6.2.2: CALDAV:calendar-user-address-set.
        - RFC 4791 Section 5.2.3: CALDAV:supported-calendar-component-set.
        - RFC 4791 Section 5.2.5: CALDAV:max-resource-size.
    """
    p_info = target.principal or _DEFAULT_PRINCIPAL

    if ns == DAV:
        if tag == DavProp.RESOURCETYPE:
            return _build_resourcetype_property(target.kind)

        if tag == DavProp.GETETAG:
            if target.etag:
                etag_elem = ET.Element(qname(DAV, DavProp.GETETAG))
                etag_elem.text = f'"{target.etag.strip('"')}"'
                return etag_elem
            return None

        if tag == DavProp.CURRENT_USER_PRINCIPAL:
            return _build_href_property(
                DAV, DavProp.CURRENT_USER_PRINCIPAL, p_info.principal_path
            )

        if tag == DavProp.PRINCIPAL_URL:
            return _build_href_property(
                DAV, DavProp.PRINCIPAL_URL, p_info.principal_path
            )

        if tag == DavProp.OWNER:
            return _build_href_property(DAV, DavProp.OWNER, p_info.principal_path)

        if tag == DavProp.CURRENT_USER_PRIVILEGE_SET:
            return _build_current_user_privilege_set_property()

        if tag == DavProp.SUPPORTED_REPORT_SET:
            return _build_supported_report_set_property(target.kind)

        if tag == DavProp.DISPLAYNAME:
            dn = ET.Element(qname(DAV, DavProp.DISPLAYNAME))
            display_text = (
                target.displayname
                or target.href.strip("/").split("/")[-1]
                or "Calendar"
            )
            dn.text = display_text
            return dn

    elif ns == CALDAV:
        if tag == CalDavProp.CALENDAR_HOME_SET:
            return _build_href_property(
                CALDAV, CalDavProp.CALENDAR_HOME_SET, p_info.calendar_home_path
            )

        if tag == CalDavProp.CALENDAR_USER_ADDRESS_SET:
            return _build_href_property(
                CALDAV, CalDavProp.CALENDAR_USER_ADDRESS_SET, p_info.email
            )

        if tag == CalDavProp.SUPPORTED_CALENDAR_COMPONENT_SET:
            if target.kind == ResourceKind.CALENDAR:
                sccs = ET.Element(
                    qname(CALDAV, CalDavProp.SUPPORTED_CALENDAR_COMPONENT_SET)
                )
                for comp in DEFAULT_SUPPORTED_COMPONENTS:
                    ET.SubElement(sccs, qname(CALDAV, "comp"), attrib={"name": comp})
                return sccs
            return None

        if tag == CalDavProp.MAX_RESOURCE_SIZE:
            if target.kind == ResourceKind.CALENDAR:
                mrs = ET.Element(qname(CALDAV, CalDavProp.MAX_RESOURCE_SIZE))
                mrs.text = "10485760"
                return mrs
            return None

    elif ns == CALSERVER:
        if tag == CalServerProp.GETCTAG:
            if target.kind == ResourceKind.CALENDAR:
                ctag_val = target.ctag or f'"ctag-{abs(hash(target.href))}"'
                ctag_elem = ET.Element(qname(CALSERVER, CalServerProp.GETCTAG))
                ctag_elem.text = ctag_val
                return ctag_elem
            return None

    return None


def _append_propstat(
    resp: ET.Element,
    elements: list[ET.Element],
    status_text: str,
) -> None:
    """Helper to append a <DAV:propstat> XML block to a <DAV:response> element."""
    if not elements:
        return
    propstat = ET.SubElement(resp, qname(DAV, "propstat"))
    prop = ET.SubElement(propstat, qname(DAV, "prop"))
    for elem in elements:
        prop.append(elem)
    status = ET.SubElement(propstat, qname(DAV, "status"))
    status.text = status_text


def append_propfind_response(
    root: ET.Element,
    target: ResourceTarget,
    requested_props: list[tuple[str, str]] | None = None,
) -> None:
    """Append a single <DAV:response> element to a <DAV:multistatus> root XML element.

    RFC References:
        - RFC 4918 Section 9.1 & 14.22: 200 OK and 404 Not Found propstat status groups.
        - RFC 5397 Section 3: DAV:current-user-principal.
        - RFC 4791 Section 5.2.3: CALDAV:supported-calendar-component-set.
        - RFC 4791 Section 6.2.1: CALDAV:calendar-home-set.
    """
    resp = ET.SubElement(root, qname(DAV, "response"))
    ET.SubElement(resp, qname(DAV, "href")).text = target.href

    if requested_props is None:
        default_props = [
            (DAV, DavProp.RESOURCETYPE),
            (DAV, DavProp.DISPLAYNAME),
            (DAV, DavProp.OWNER),
            (DAV, DavProp.CURRENT_USER_PRINCIPAL),
            (DAV, DavProp.CURRENT_USER_PRIVILEGE_SET),
            (CALDAV, CalDavProp.CALENDAR_HOME_SET),
        ]
        if target.kind == ResourceKind.CALENDAR:
            default_props.append((CALDAV, CalDavProp.SUPPORTED_CALENDAR_COMPONENT_SET))
            default_props.append((CALDAV, CalDavProp.MAX_RESOURCE_SIZE))
            default_props.append((DAV, DavProp.SUPPORTED_REPORT_SET))
            default_props.append((CALSERVER, CalServerProp.GETCTAG))
        if target.etag:
            default_props.append((DAV, DavProp.GETETAG))

        supported_elems = [
            elem
            for ns, tag in default_props
            if (elem := create_property_element(ns, tag, target)) is not None
        ]
        _append_propstat(resp, supported_elems, "HTTP/1.1 200 OK")
    else:
        supported_elems: list[ET.Element] = []
        unsupported_elems: list[ET.Element] = []

        for ns, tag in requested_props:
            elem = create_property_element(ns, tag, target)
            if elem is not None:
                supported_elems.append(elem)
            else:
                unsupported_elems.append(ET.Element(qname(ns, tag)))

        _append_propstat(resp, supported_elems, "HTTP/1.1 200 OK")
        _append_propstat(resp, unsupported_elems, "HTTP/1.1 404 Not Found")


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
