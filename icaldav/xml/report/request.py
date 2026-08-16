"""CalDAV REPORT XML request building and parsing.

RFC Reference:
    - RFC 4791 Section 7.8: CALDAV:calendar-query REPORT.
    - RFC 4791 Section 7.9: CALDAV:calendar-multiget REPORT.
"""

import xml.etree.ElementTree as ET

from icaldav.engine.models import (
    CalendarMultigetQuery,
    CalendarQuery,
    PrincipalSearchQuery,
    PropertyTag,
    SearchCriteria,
    SyncCollectionQuery,
)
from icaldav.filter import CompFilter, TimeRange
from icaldav.xml.namespaces import CALDAV, DAV, qname, strip_ns


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


def _parse_props(prop_elem: ET.Element) -> list[PropertyTag]:
    """Extract PropertyTag list from a <D:prop> element."""
    props = []
    for child in prop_elem:
        tag = child.tag
        if tag.startswith("{") and "}" in tag:
            ns, local_tag = tag[1:].split("}", 1)
            props.append(PropertyTag(ns, local_tag))
        else:
            # Map calendar-data to CALDAV namespace as fallback
            ns = CALDAV if strip_ns(tag) == "calendar-data" else DAV
            props.append(PropertyTag(ns, strip_ns(tag)))
    return props


def parse_report_root_tag(xml_bytes: bytes) -> str:
    """Inspect and return the root tag name of a REPORT request XML body, namespace-stripped.

    Args:
        xml_bytes: Raw XML request byte payload.

    Returns:
        The namespace-stripped root tag name string, or empty string if invalid.
    """
    if not xml_bytes or not xml_bytes.strip():
        return ""
    try:
        root = ET.fromstring(xml_bytes)
        return strip_ns(root.tag)
    except ET.ParseError:
        return ""


def parse_calendar_query(xml_bytes: bytes) -> CalendarQuery:
    """Parse a <C:calendar-query> REPORT request XML body into a CalendarQuery IR object."""
    root = ET.fromstring(xml_bytes)

    props: list[PropertyTag] = []
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

    return CalendarQuery(props=props, comp_filter=comp_filter)


def parse_calendar_multiget(xml_bytes: bytes) -> CalendarMultigetQuery:
    """Parse a <C:calendar-multiget> REPORT request XML body into a CalendarMultigetQuery IR object."""
    root = ET.fromstring(xml_bytes)

    props: list[PropertyTag] = []
    hrefs: list[str] = []

    for child in root:
        tag = strip_ns(child.tag)
        if tag == "prop":
            props = _parse_props(child)
        elif tag == "href" and child.text:
            hrefs.append(child.text.strip())

    return CalendarMultigetQuery(props=props, hrefs=hrefs)


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


def build_principal_property_search_xml(
    match: str,
    prop_tag: str = "displayname",
) -> bytes:
    """Build a <DAV:principal-property-search> REPORT request XML body (RFC 3744 §9.4)."""
    root = ET.Element(qname(DAV, "principal-property-search"))
    ps_elem = ET.SubElement(root, qname(DAV, "property-search"))
    prop_elem = ET.SubElement(ps_elem, qname(DAV, "prop"))
    ET.SubElement(prop_elem, qname(DAV, prop_tag))
    match_elem = ET.SubElement(ps_elem, qname(DAV, "match"))
    match_elem.text = match
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def build_sync_collection_xml(
    sync_token: str = "",
    limit: int | None = None,
) -> bytes:
    """Build a <DAV:sync-collection> REPORT request XML body (RFC 6578 §3)."""
    root = ET.Element(qname(DAV, "sync-collection"))
    st_elem = ET.SubElement(root, qname(DAV, "sync-token"))
    st_elem.text = sync_token

    if limit is not None:
        limit_elem = ET.SubElement(root, qname(DAV, "limit"))
        nres_elem = ET.SubElement(limit_elem, qname(DAV, "nresults"))
        nres_elem.text = str(limit)
    prop_elem = ET.SubElement(root, qname(DAV, "prop"))
    ET.SubElement(prop_elem, qname(DAV, "getetag"))
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _parse_search_criterion(criterion_elem: ET.Element) -> SearchCriteria | None:
    prop_tag = ""
    match_str = ""
    for child in criterion_elem:
        tag = strip_ns(child.tag)
        if tag == "prop":
            for p in child:
                prop_tag = strip_ns(p.tag)
        elif tag == "match" and child.text:
            match_str = child.text.strip()
    if prop_tag and match_str:
        return SearchCriteria(prop_tag=prop_tag, match=match_str)
    return None


def parse_principal_property_search(xml_bytes: bytes) -> PrincipalSearchQuery:
    """Parse a <DAV:principal-property-search> REPORT request XML body into a PrincipalSearchQuery IR object."""
    if not xml_bytes or not xml_bytes.strip():
        return PrincipalSearchQuery(criteria=[], props=[])

    root = ET.fromstring(xml_bytes)
    criteria: list[SearchCriteria] = []
    props: list[PropertyTag] = []

    for child in root:
        tag = strip_ns(child.tag)
        if tag == "prop":
            props = _parse_props(child)
        elif tag == "property-search":
            crit = _parse_search_criterion(child)
            if crit is not None:
                criteria.append(crit)

    return PrincipalSearchQuery(criteria=criteria, props=props)


def parse_sync_collection(xml_bytes: bytes) -> SyncCollectionQuery:
    """Parse a <DAV:sync-collection> REPORT request XML body into a SyncCollectionQuery IR object."""
    if not xml_bytes or not xml_bytes.strip():
        return SyncCollectionQuery(sync_token="")

    root = ET.fromstring(xml_bytes)
    sync_token = ""
    limit: int | None = None

    for child in root:
        tag = strip_ns(child.tag)
        if tag == "sync-token" and child.text:
            sync_token = child.text.strip()
        elif tag == "limit":
            for nres in child:
                if strip_ns(nres.tag) == "nresults" and nres.text:
                    try:
                        limit = int(nres.text.strip())
                    except ValueError:
                        pass

    return SyncCollectionQuery(sync_token=sync_token, limit=limit)
