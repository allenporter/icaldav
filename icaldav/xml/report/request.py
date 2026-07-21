"""CalDAV REPORT XML request building and parsing.

RFC Reference:
    - RFC 4791 Section 7.8: CALDAV:calendar-query REPORT.
    - RFC 4791 Section 7.9: CALDAV:calendar-multiget REPORT.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from icaldav.filter import CompFilter, TimeRange
from icaldav.xml.namespaces import CALDAV, DAV, qname, strip_ns
from icaldav.xml.report.models import CalendarMultigetRequest, CalendarQueryRequest


def _parse_comp_filter(elem: ET.Element) -> CompFilter:
    """Recursively parse a <C:comp-filter> element into a CompFilter dataclass."""
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
    """Extract property local names from a <D:prop> element."""
    return [strip_ns(child.tag) for child in prop_elem]


def parse_calendar_query(xml_bytes: bytes) -> CalendarQueryRequest:
    """Parse a <C:calendar-query> REPORT request XML body."""
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
    """Parse a <C:calendar-multiget> REPORT request XML body."""
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


def build_calendar_query_xml(
    component: str = "VEVENT",
    time_start: str | None = None,
    time_end: str | None = None,
    props: list[str] | None = None,
) -> bytes:
    """Build a <C:calendar-query> REPORT request XML body."""
    if props is None:
        props = ["getetag", "calendar-data"]

    root = ET.Element(qname(CALDAV, "calendar-query"))

    prop_elem = ET.SubElement(root, qname(DAV, "prop"))
    for prop_name in props:
        ns = CALDAV if prop_name == "calendar-data" else DAV
        ET.SubElement(prop_elem, qname(ns, prop_name))

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
    """Build a <C:calendar-multiget> REPORT request XML body."""
    if props is None:
        props = ["getetag", "calendar-data"]

    root = ET.Element(qname(CALDAV, "calendar-multiget"))

    prop_elem = ET.SubElement(root, qname(DAV, "prop"))
    for prop_name in props:
        ns = CALDAV if prop_name == "calendar-data" else DAV
        ET.SubElement(prop_elem, qname(ns, prop_name))

    for href in hrefs:
        href_elem = ET.SubElement(root, qname(DAV, "href"))
        href_elem.text = href

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
