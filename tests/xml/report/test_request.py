"""Unit tests for CalDAV REPORT XML request generation and parsing."""

import pytest

from icaldav.engine.models import (
    CalendarMultigetQuery,
    CalendarQuery,
)
from icaldav.xml.report.request import (
    build_calendar_multiget_xml,
    build_calendar_query_xml,
    parse_calendar_multiget,
    parse_calendar_query,
    parse_principal_property_search,
)


def test_build_and_parse_calendar_query() -> None:
    """Test building and parsing a calendar-query REPORT XML body."""
    xml_bytes = build_calendar_query_xml(
        component="VEVENT",
        time_start="20260701T000000Z",
        time_end="20260801T000000Z",
        props=["getetag", "calendar-data"],
    )
    assert b"calendar-query" in xml_bytes
    assert b"20260701T000000Z" in xml_bytes

    req = parse_calendar_query(xml_bytes)
    assert isinstance(req, CalendarQuery)
    prop_names = [p.name for p in req.props]
    assert "getetag" in prop_names
    assert "calendar-data" in prop_names
    assert req.comp_filter.name == "VCALENDAR"
    assert len(req.comp_filter.comp_filters) == 1
    vevent_filter = req.comp_filter.comp_filters[0]
    assert vevent_filter.name == "VEVENT"
    assert vevent_filter.time_range is not None
    assert vevent_filter.time_range.start == "20260701T000000Z"
    assert vevent_filter.time_range.end == "20260801T000000Z"


def test_parse_calendar_query_invalid() -> None:
    """Test parse_calendar_query raises ValueError when missing required filter."""
    invalid_xml = b"""<?xml version="1.0" encoding="utf-8"?>
    <c:calendar-query xmlns:c="urn:ietf:params:xml:ns:caldav" xmlns:d="DAV:">
        <d:prop><d:getetag/></d:prop>
    </c:calendar-query>
    """
    with pytest.raises(ValueError, match="missing required"):
        parse_calendar_query(invalid_xml)


def test_build_and_parse_calendar_multiget() -> None:
    """Test building and parsing a calendar-multiget REPORT XML body."""
    hrefs = ["/work/event1.ics", "/work/event2.ics"]
    xml_bytes = build_calendar_multiget_xml(hrefs=hrefs)
    assert b"calendar-multiget" in xml_bytes
    assert b"/work/event1.ics" in xml_bytes

    req = parse_calendar_multiget(xml_bytes)
    assert isinstance(req, CalendarMultigetQuery)
    assert req.hrefs == hrefs
    prop_names = [p.name for p in req.props]
    assert "getetag" in prop_names
    assert "calendar-data" in prop_names


def test_parse_principal_property_search() -> None:
    """Test parsing a principal-property-search REPORT XML request."""
    search_xml = b"""<?xml version="1.0" encoding="utf-8"?>
    <d:principal-property-search xmlns:d="DAV:">
        <d:property-search>
            <d:prop><d:displayname/></d:prop>
            <d:match>bernard</d:match>
        </d:property-search>
    </d:principal-property-search>
    """
    req = parse_principal_property_search(search_xml)
    assert len(req.criteria) == 1
    assert req.criteria[0].prop_tag == "displayname"
    assert req.criteria[0].match == "bernard"

    assert parse_principal_property_search(b"").criteria == []
