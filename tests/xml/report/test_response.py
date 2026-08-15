"""Unit tests for CalDAV REPORT Multi-Status XML response generation and parsing."""

from icaldav.store.types import ReportResource
from icaldav.xml.report.response import (
    build_report_response,
    parse_report_response,
)


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
