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
        missing_list = list(resources.missing_hrefs) + list(resources.deleted_hrefs)
        sync_token = resources.sync_token
    else:
        res_list = resources
        missing_list = missing_hrefs or []
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

    if sync_token is not None:
        st_elem = ET.SubElement(root, qname(DAV, "sync-token"))
        st_elem.text = sync_token

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def parse_report_response(xml_bytes: bytes) -> list[ReportResource]:
    """Parse a 207 Multi-Status XML response from a REPORT request."""
    if not xml_bytes or not xml_bytes.strip():
        return []

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        _LOGGER.debug("Failed to parse REPORT response XML", exc_info=True)
        return []

    resources: list[ReportResource] = []

    for resp_elem in root:
        if strip_ns(resp_elem.tag) != "response":
            continue

        href = ""
        etag = ""
        ics_data: str | None = None
        is_ok = False

        for child in resp_elem:
            tag = strip_ns(child.tag)
            if tag == "href" and child.text:
                href = child.text.strip()
            elif tag == "propstat":
                for ps_child in child:
                    ps_tag = strip_ns(ps_child.tag)
                    if ps_tag == "status" and ps_child.text:
                        is_ok = "200" in ps_child.text
                    elif ps_tag == "prop":
                        for prop_child in ps_child:
                            prop_tag = strip_ns(prop_child.tag)
                            if prop_tag == "getetag" and prop_child.text:
                                etag = prop_child.text.strip().strip('"')
                            elif prop_tag == "calendar-data" and prop_child.text:
                                ics_data = prop_child.text

        if href and is_ok:
            resources.append(ReportResource(href=href, etag=etag, ics_data=ics_data))

    return resources


def parse_sync_collection_response(
    xml_bytes: bytes,
) -> tuple[list[ReportResource], str | None]:
    """Parse a 207 Multi-Status XML response from an RFC 6578 sync-collection REPORT.

    Returns:
        Tuple of (resources list, server sync token if present).
    """
    resources = parse_report_response(xml_bytes)
    if not xml_bytes or not xml_bytes.strip():
        return resources, None

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return resources, None

    sync_token: str | None = None
    for child in root:
        if strip_ns(child.tag) == "sync-token" and child.text:
            sync_token = child.text.strip()
            break

    return resources, sync_token
