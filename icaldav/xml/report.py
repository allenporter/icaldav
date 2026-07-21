"""CalDAV REPORT XML request/response generation and parsing.

Handles XML processing for the two CalDAV REPORT methods:
  1. calendar-query (RFC 4791 §7.8): Filter-based search returning matching resources.
  2. calendar-multiget (RFC 4791 §7.9): Batch retrieval of specific resources by href.

REPORT Lifecycle:
  Client-side (request building):
    1. Client constructs a <C:calendar-query> or <C:calendar-multiget> XML body.
    2. Client sends HTTP REPORT to the target collection URL.
    3. Client parses the 207 Multi-Status response to extract resources.

  Server-side (request parsing + response building):
    1. Server receives REPORT request and parses the XML body.
    2. For calendar-query: evaluates filter against stored resources.
    3. For calendar-multiget: resolves each requested href.
    4. Server builds a 207 Multi-Status XML response with matching resources.

RFC References:
  - RFC 4791 Section 7.8: CALDAV:calendar-query REPORT.
  - RFC 4791 Section 7.9: CALDAV:calendar-multiget REPORT.
  - RFC 4791 Section 9.5: CALDAV:calendar-data element.
  - RFC 4791 Section 9.7: CALDAV:comp-filter element.
  - RFC 4791 Section 9.9: CALDAV:time-range element.
  - RFC 4918 Section 13: DAV:multistatus response body.
  - RFC 3253 Section 3.6: REPORT method definition.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import xml.etree.ElementTree as ET

from icaldav.filter import CompFilter, TimeRange
from icaldav.xml.namespaces import CALDAV, DAV, qname, strip_ns

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclasses for parsed REPORT requests and response resources
# ---------------------------------------------------------------------------


@dataclass
class CalendarQueryRequest:
    """Parsed representation of a <C:calendar-query> REPORT request body (RFC 4791 §7.8).

    Produced by ``parse_calendar_query()`` from the raw XML sent by a CalDAV client.
    The server uses this to determine which properties to return and which filter
    criteria to evaluate against stored iCalendar resources.

    Attributes:
        props: List of property local names requested by the client.
        comp_filter: Root component filter tree to evaluate against stored resources.
    """

    props: list[str]
    """Property local names requested in <D:prop> (e.g. ['getetag', 'calendar-data']).

    The server returns these properties for each matching resource in the
    207 Multi-Status response. Common values:
      - 'getetag': Resource version tag (RFC 4918 §14.19).
      - 'calendar-data': Raw iCalendar content (RFC 4791 §9.5).
    """

    comp_filter: CompFilter
    """Root component filter tree parsed from <C:filter> (RFC 4791 §9.7).

    The top-level comp-filter MUST have name='VCALENDAR'. Nested comp-filters
    specify which component types (VEVENT, VTODO) and optional time-range
    constraints to match against.
    """


@dataclass
class CalendarMultigetRequest:
    """Parsed representation of a <C:calendar-multiget> REPORT request body (RFC 4791 §7.9).

    Produced by ``parse_calendar_multiget()`` from the raw XML sent by a CalDAV client.
    The server uses this to batch-retrieve specific resources by their hrefs.

    Attributes:
        props: List of property local names requested by the client.
        hrefs: List of resource href paths to retrieve.
    """

    props: list[str]
    """Property local names requested in <D:prop> (e.g. ['getetag', 'calendar-data']).

    Same semantics as CalendarQueryRequest.props.
    """

    hrefs: list[str]
    """Absolute or relative URI paths of resources to retrieve (RFC 4791 §7.9).

    Each href corresponds to a calendar object resource (e.g. '/work/event1.ics').
    The server resolves each href and returns 200 OK with properties for existing
    resources, or 404 Not Found for missing ones.
    """


@dataclass
class ReportResource:
    """A single resource entry in a REPORT 207 Multi-Status response.

    Used both when building server responses and when parsing client responses.
    Carries the resource's href, ETag, and optionally the raw iCalendar content.

    Attributes:
        href: Resource URI path.
        etag: Entity tag for version tracking.
        ics_data: Raw iCalendar content, if requested via calendar-data property.
    """

    href: str
    """Relative URI path of the calendar resource (e.g. '/work/event1.ics').

    Corresponds to the <D:href> element in the multi-status response.
    RFC 4918 §14.7.
    """

    etag: str
    """Entity tag representing the current version of the resource.

    Returned inside <D:getetag> in the response propstat.
    RFC 4918 §14.19.
    """

    ics_data: str | None = None
    """Raw RFC 5545 iCalendar content of the resource, if requested.

    Returned inside <C:calendar-data> in the response propstat.
    Only populated when the client requests the 'calendar-data' property.
    RFC 4791 §9.5.
    """


# ---------------------------------------------------------------------------
# Server-side: Parse incoming REPORT XML request bodies
# ---------------------------------------------------------------------------


def _parse_comp_filter(elem: ET.Element) -> CompFilter:
    """Recursively parse a <C:comp-filter> element into a CompFilter dataclass.

    RFC Reference:
        - RFC 4791 Section 9.7: CALDAV:comp-filter XML Element Definition.

    Args:
        elem: An ElementTree element representing <C:comp-filter>.

    Returns:
        A CompFilter dataclass with nested filters and optional time range.
    """
    name = elem.get("name", "")
    time_range: TimeRange | None = None
    comp_filters: list[CompFilter] = []

    for child in elem:
        tag = strip_ns(child.tag)
        if tag == "time-range":
            time_range = TimeRange(
                start=child.get("start"),
                end=child.get("end"),
            )
        elif tag == "comp-filter":
            comp_filters.append(_parse_comp_filter(child))

    return CompFilter(
        name=name,
        time_range=time_range,
        comp_filters=comp_filters,
    )


def _parse_props(prop_elem: ET.Element) -> list[str]:
    """Extract property local names from a <D:prop> element.

    Args:
        prop_elem: An ElementTree element representing <D:prop>.

    Returns:
        List of property local name strings (e.g. ['getetag', 'calendar-data']).
    """
    return [strip_ns(child.tag) for child in prop_elem]


def parse_calendar_query(xml_bytes: bytes) -> CalendarQueryRequest:
    """Parse a <C:calendar-query> REPORT request XML body.

    Extracts the requested properties from <D:prop> and the component filter
    tree from <C:filter>. The filter tree is used by the server to evaluate
    which stored resources match the client's query criteria.

    RFC Reference:
        - RFC 4791 Section 7.8: CALDAV:calendar-query REPORT.

    Args:
        xml_bytes: Raw XML request body bytes.

    Returns:
        A CalendarQueryRequest dataclass with parsed properties and filter.

    Raises:
        ValueError: If the XML is missing required <C:filter> or <C:comp-filter>.
    """
    root = ET.fromstring(xml_bytes)

    props: list[str] = []
    comp_filter: CompFilter | None = None

    for child in root:
        tag = strip_ns(child.tag)
        if tag == "prop":
            props = _parse_props(child)
        elif tag == "filter":
            for filter_child in child:
                if strip_ns(filter_child.tag) == "comp-filter":
                    comp_filter = _parse_comp_filter(filter_child)
                    break

    if comp_filter is None:
        raise ValueError(
            "calendar-query REPORT missing required <C:filter>/<C:comp-filter>"
        )

    return CalendarQueryRequest(props=props, comp_filter=comp_filter)


def parse_calendar_multiget(xml_bytes: bytes) -> CalendarMultigetRequest:
    """Parse a <C:calendar-multiget> REPORT request XML body.

    Extracts the requested properties from <D:prop> and the list of resource
    hrefs from <D:href> elements.

    RFC Reference:
        - RFC 4791 Section 7.9: CALDAV:calendar-multiget REPORT.

    Args:
        xml_bytes: Raw XML request body bytes.

    Returns:
        A CalendarMultigetRequest dataclass with parsed properties and hrefs.
    """
    root = ET.fromstring(xml_bytes)

    props: list[str] = []
    hrefs: list[str] = []

    for child in root:
        tag = strip_ns(child.tag)
        if tag == "prop":
            props = _parse_props(child)
        elif tag == "href":
            if child.text:
                hrefs.append(child.text.strip())

    return CalendarMultigetRequest(props=props, hrefs=hrefs)


# ---------------------------------------------------------------------------
# Server-side: Build REPORT 207 Multi-Status XML response
# ---------------------------------------------------------------------------


def build_report_response(
    resources: list[ReportResource],
    missing_hrefs: list[str] | None = None,
) -> bytes:
    """Build a 207 Multi-Status XML response body for a REPORT result.

    Constructs a <D:multistatus> response containing a <D:response> element
    for each resource. Found resources include <D:getetag> and optionally
    <C:calendar-data> inside a 200 OK propstat. Missing hrefs (for
    calendar-multiget) are included with a 404 Not Found propstat.

    RFC Reference:
        - RFC 4918 Section 13: Multi-Status Response.
        - RFC 4791 Section 9.5: CALDAV:calendar-data XML Element.

    Args:
        resources: List of ReportResource objects for found resources.
        missing_hrefs: Optional list of href strings that were not found.

    Returns:
        XML response body as bytes.
    """
    root = ET.Element(qname(DAV, "multistatus"))

    for resource in resources:
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

    for href in missing_hrefs or []:
        resp = ET.SubElement(root, qname(DAV, "response"))
        href_elem = ET.SubElement(resp, qname(DAV, "href"))
        href_elem.text = href

        propstat = ET.SubElement(resp, qname(DAV, "propstat"))
        status = ET.SubElement(propstat, qname(DAV, "status"))
        status.text = "HTTP/1.1 404 Not Found"

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


# ---------------------------------------------------------------------------
# Client-side: Build REPORT XML request bodies
# ---------------------------------------------------------------------------


def build_calendar_query_xml(
    component: str = "VEVENT",
    time_start: str | None = None,
    time_end: str | None = None,
    props: list[str] | None = None,
) -> bytes:
    """Build a <C:calendar-query> REPORT request XML body.

    Constructs a calendar-query request that filters resources by component type
    and optional time range. The default request asks for getetag and calendar-data
    properties.

    RFC Reference:
        - RFC 4791 Section 7.8: CALDAV:calendar-query REPORT.

    Args:
        component: iCalendar component name to filter (e.g. 'VEVENT', 'VTODO').
        time_start: Optional UTC start boundary (e.g. '20260701T000000Z').
        time_end: Optional UTC end boundary (e.g. '20260801T000000Z').
        props: Optional list of property names to request. Defaults to
               ['getetag', 'calendar-data'].

    Returns:
        XML request body as bytes.
    """
    if props is None:
        props = ["getetag", "calendar-data"]

    root = ET.Element(qname(CALDAV, "calendar-query"))

    # <D:prop>
    prop_elem = ET.SubElement(root, qname(DAV, "prop"))
    for prop_name in props:
        ns = CALDAV if prop_name == "calendar-data" else DAV
        ET.SubElement(prop_elem, qname(ns, prop_name))

    # <C:filter>
    filter_elem = ET.SubElement(root, qname(CALDAV, "filter"))
    vcal_filter = ET.SubElement(
        filter_elem,
        qname(CALDAV, "comp-filter"),
        attrib={"name": "VCALENDAR"},
    )

    comp_filter_attrib: dict[str, str] = {"name": component}
    comp_elem = ET.SubElement(
        vcal_filter, qname(CALDAV, "comp-filter"), attrib=comp_filter_attrib
    )

    if time_start or time_end:
        tr_attrib: dict[str, str] = {}
        if time_start:
            tr_attrib["start"] = time_start
        if time_end:
            tr_attrib["end"] = time_end
        ET.SubElement(comp_elem, qname(CALDAV, "time-range"), attrib=tr_attrib)

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def build_calendar_multiget_xml(
    hrefs: list[str],
    props: list[str] | None = None,
) -> bytes:
    """Build a <C:calendar-multiget> REPORT request XML body.

    Constructs a calendar-multiget request that retrieves specific resources
    by their href paths in a single round-trip.

    RFC Reference:
        - RFC 4791 Section 7.9: CALDAV:calendar-multiget REPORT.

    Args:
        hrefs: List of resource href paths to retrieve.
        props: Optional list of property names to request. Defaults to
               ['getetag', 'calendar-data'].

    Returns:
        XML request body as bytes.
    """
    if props is None:
        props = ["getetag", "calendar-data"]

    root = ET.Element(qname(CALDAV, "calendar-multiget"))

    # <D:prop>
    prop_elem = ET.SubElement(root, qname(DAV, "prop"))
    for prop_name in props:
        ns = CALDAV if prop_name == "calendar-data" else DAV
        ET.SubElement(prop_elem, qname(ns, prop_name))

    # <D:href> elements
    for href in hrefs:
        href_elem = ET.SubElement(root, qname(DAV, "href"))
        href_elem.text = href

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


# ---------------------------------------------------------------------------
# Client-side: Parse REPORT 207 Multi-Status XML response
# ---------------------------------------------------------------------------


def parse_report_response(xml_bytes: bytes) -> list[ReportResource]:
    """Parse a 207 Multi-Status XML response from a REPORT request.

    Extracts resource hrefs, ETags, and optional calendar-data from each
    <D:response> element in the multi-status response. Only responses with
    HTTP 200 OK status are included.

    RFC Reference:
        - RFC 4918 Section 13: Multi-Status Response.
        - RFC 4791 Section 9.5: CALDAV:calendar-data element.

    Args:
        xml_bytes: Raw XML response body bytes.

    Returns:
        List of ReportResource objects for successfully retrieved resources.
    """
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
