"""Unit tests for CalDAV REPORT Multi-Status XML response generation and parsing."""

from icaldav.store.types import ReportResource
from icaldav.xml.report.response import (
    build_report_response,
    parse_report_response,
    parse_sync_collection_response,
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


def test_parse_report_response_multi_propstat() -> None:
    """Test that a trailing 404 propstat does not clobber a valid 200 propstat."""
    multi_propstat_xml = b"""<?xml version="1.0" encoding="utf-8"?>
    <d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
        <d:response>
            <d:href>/work/event1.ics</d:href>
            <d:propstat>
                <d:prop>
                    <d:getetag>"etag-abc"</d:getetag>
                    <c:calendar-data>BEGIN:VCALENDAR\r\nUID:abc\r\nEND:VCALENDAR</c:calendar-data>
                </d:prop>
                <d:status>HTTP/1.1 200 OK</d:status>
            </d:propstat>
            <d:propstat>
                <d:prop>
                    <d:Schedule-Tag/>
                </d:prop>
                <d:status>HTTP/1.1 404 Not Found</d:status>
            </d:propstat>
        </d:response>
    </d:multistatus>
    """
    parsed = parse_report_response(multi_propstat_xml)
    assert len(parsed) == 1
    assert parsed[0].href == "/work/event1.ics"
    assert parsed[0].etag == "etag-abc"
    assert parsed[0].ics_data is not None
    assert "UID:abc" in parsed[0].ics_data
    assert parsed[0].deleted is False

    sync_parsed, token = parse_sync_collection_response(
        b"""<?xml version="1.0" encoding="utf-8"?>
        <d:multistatus xmlns:d="DAV:">
            <d:response>
                <d:href>/work/deleted_rfc6578.ics</d:href>
                <d:status>HTTP/1.1 404 Not Found</d:status>
            </d:response>
            <d:response>
                <d:href>/work/deleted_propstat.ics</d:href>
                <d:propstat>
                    <d:status>HTTP/1.1 404 Not Found</d:status>
                </d:propstat>
            </d:response>
            <d:sync-token>http://example.com/ns/sync/42</d:sync-token>
        </d:multistatus>
        """
    )
    assert token == "http://example.com/ns/sync/42"
    assert [(r.href, r.deleted) for r in sync_parsed] == [
        ("/work/deleted_rfc6578.ics", True),
        ("/work/deleted_propstat.ics", True),
    ]
