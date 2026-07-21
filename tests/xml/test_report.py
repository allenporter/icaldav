"""Unit tests for CalDAV REPORT XML generation and parsing."""

import pytest

from icaldav.xml.report.models import (
    CalendarMultigetRequest,
    CalendarQueryRequest,
    ReportResource,
)
from icaldav.xml.report.request import (
    build_calendar_multiget_xml,
    build_calendar_query_xml,
    parse_calendar_multiget,
    parse_calendar_query,
)
from icaldav.xml.report.response import (
    build_report_response,
    parse_report_response,
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
    assert isinstance(req, CalendarQueryRequest)
    assert "getetag" in req.props
    assert "calendar-data" in req.props
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
    assert isinstance(req, CalendarMultigetRequest)
    assert req.hrefs == hrefs
    assert "getetag" in req.props
    assert "calendar-data" in req.props


def test_build_and_parse_report_response() -> None:
    """Test building a 207 Multi-Status response with resources and missing hrefs, and parsing it."""
    resources = [
        ReportResource(
            href="/work/event1.ics",
            etag='"etag-123"',
            ics_data="BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:1\r\nEND:VEVENT\r\nEND:VCALENDAR",
        )
    ]
    missing = ["/work/missing.ics"]

    response_xml = build_report_response(resources=resources, missing_hrefs=missing)
    assert b"multistatus" in response_xml
    assert b"/work/event1.ics" in response_xml
    assert b"404 Not Found" in response_xml

    parsed = parse_report_response(response_xml)
    assert len(parsed) == 1
    assert parsed[0].href == "/work/event1.ics"
    assert parsed[0].etag == "etag-123"
    assert parsed[0].ics_data is not None
    assert "UID:1" in parsed[0].ics_data


def test_parse_report_response_edge_cases() -> None:
    """Test parse_report_response with empty XML, malformed XML, and non-200 responses."""
    # Empty bytes
    assert parse_report_response(b"") == []
    assert parse_report_response(b"   ") == []

    # Malformed XML
    assert parse_report_response(b"<invalid xml payload") == []

    # XML with non-200 propstat only
    non_200_xml = b"""<?xml version="1.0" encoding="utf-8"?>
    <d:multistatus xmlns:d="DAV:">
        <d:response>
            <d:href>/work/missing.ics</d:href>
            <d:propstat>
                <d:status>HTTP/1.1 404 Not Found</d:status>
            </d:propstat>
        </d:response>
    </d:multistatus>
    """
    assert parse_report_response(non_200_xml) == []
