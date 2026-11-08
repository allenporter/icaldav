"""CalDAV REPORT XML response building and parsing.

RFC Reference:
    - RFC 4918 Section 13: Multi-Status Response.
    - RFC 4791 Section 9.5: CALDAV:calendar-data XML Element.
"""

import logging
import xml.etree.ElementTree as ET

from icaldav.engine.models import ReportMultiStatus
from icaldav.store.types import ReportResource
from icaldav.xml.namespaces import CALDAV, DAV, qname, strip_ns

_LOGGER = logging.getLogger(__name__)


def build_report_response(
    resources: list[ReportResource] | ReportMultiStatus,
    missing_hrefs: list[str] | None = None,
) -> bytes:
    """Build a 207 Multi-Status XML response body for a REPORT result.

    Args:
        resources: Either a list of ReportResource objects or a ReportMultiStatus IR object.
        missing_hrefs: Optional list of missing resource URIs (if passing a resources list).

    Returns:
        Encoded UTF-8 XML byte string representation of the Multi-Status response.
    """
    if isinstance(resources, ReportMultiStatus):
        res_list = resources.responses
        missing_list = list(resources.missing_hrefs)
        deleted_list = list(resources.deleted_hrefs)
        sync_token = resources.sync_token
    else:
        res_list = resources
        missing_list = missing_hrefs or []
        deleted_list = []
        sync_token = None

    root = ET.Element(qname(DAV, "multistatus"))

    for resource in res_list:
        resp = ET.SubElement(root, qname(DAV, "response"))
        href_elem = ET.SubElement(resp, qname(DAV, "href"))
        href_elem.text = resource.href

        propstat = ET.SubElement(resp, qname(DAV, "propstat"))
        prop = ET.SubElement(propstat, qname(DAV, "prop"))

        etag_elem = ET.SubElement(prop, qname(DAV, "getetag"))
        clean_etag = resource.etag.strip('"')
        etag_elem.text = f'"{clean_etag}"'

        if resource.ics_data is not None:
            cal_data = ET.SubElement(prop, qname(CALDAV, "calendar-data"))
            cal_data.text = resource.ics_data

        status = ET.SubElement(propstat, qname(DAV, "status"))
        status.text = "HTTP/1.1 200 OK"

    for href in missing_list:
        resp = ET.SubElement(root, qname(DAV, "response"))
        href_elem = ET.SubElement(resp, qname(DAV, "href"))
        href_elem.text = href

        propstat = ET.SubElement(resp, qname(DAV, "propstat"))
        status = ET.SubElement(propstat, qname(DAV, "status"))
        status.text = "HTTP/1.1 404 Not Found"

    for href in deleted_list:
        resp = ET.SubElement(root, qname(DAV, "response"))
        href_elem = ET.SubElement(resp, qname(DAV, "href"))
        href_elem.text = href

        status = ET.SubElement(resp, qname(DAV, "status"))
        status.text = "HTTP/1.1 404 Not Found"

    if sync_token is not None:
        st_elem = ET.SubElement(root, qname(DAV, "sync-token"))
        st_elem.text = sync_token

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _parse_multistatus_response(
    xml_bytes: bytes, *, include_deleted: bool = False
) -> tuple[list[ReportResource], str | None]:
    """Parse a 207 Multi-Status XML response from a REPORT request in a single pass."""
    if not xml_bytes or not xml_bytes.strip():
        return [], None

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        _LOGGER.debug("Failed to parse REPORT response XML", exc_info=True)
        return [], None

    resources: list[ReportResource] = []
    sync_token: str | None = None

    for resp_elem in root:
        elem_tag = strip_ns(resp_elem.tag)
        if elem_tag == "sync-token" and resp_elem.text:
            sync_token = resp_elem.text.strip()
            continue
        if elem_tag != "response":
            continue

        href = ""
        etag = ""
        ics_data: str | None = None
        is_ok = False
        has_404 = False

        for child in resp_elem:
            tag = strip_ns(child.tag)
            if tag == "href" and child.text:
                href = child.text.strip()
            elif tag == "status" and child.text and "404" in child.text:
                has_404 = True
            elif tag == "propstat":
                ps_ok = False
                ps_prop: ET.Element | None = None
                for ps_child in child:
                    ps_tag = strip_ns(ps_child.tag)
                    if ps_tag == "status" and ps_child.text:
                        ps_ok = "200" in ps_child.text
                        if "404" in ps_child.text:
                            has_404 = True
                    elif ps_tag == "prop":
                        ps_prop = ps_child
                if ps_ok:
                    is_ok = True
                    if ps_prop is not None:
                        for prop_child in ps_prop:
                            prop_tag = strip_ns(prop_child.tag)
                            if prop_tag == "getetag" and prop_child.text:
                                etag = prop_child.text.strip().strip('"')
                            elif prop_tag == "calendar-data" and prop_child.text:
                                ics_data = prop_child.text

        if href and is_ok:
            resources.append(ReportResource(href=href, etag=etag, ics_data=ics_data))
        elif include_deleted and href and has_404:
            resources.append(ReportResource(href=href, etag="", deleted=True))

    return resources, sync_token


def parse_report_response(
    xml_bytes: bytes, *, include_deleted: bool = False
) -> list[ReportResource]:
    """Parse a 207 Multi-Status XML response from a REPORT request."""
    resources, _ = _parse_multistatus_response(
        xml_bytes, include_deleted=include_deleted
    )
    return resources


def parse_sync_collection_response(
    xml_bytes: bytes,
) -> tuple[list[ReportResource], str | None]:
    """Parse a 207 Multi-Status XML response from an RFC 6578 sync-collection REPORT.

    Returns:
        Tuple of (resources list, server sync token if present).
    """
    return _parse_multistatus_response(xml_bytes, include_deleted=True)
