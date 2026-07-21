"""Unit tests for PROPFIND XML generation and multi-status parsing using syrupy snapshot testing."""

from syrupy.assertion import SnapshotAssertion

from icaldav.xml.namespaces import strip_ns
from icaldav.xml.propfind import (
    build_propfind_xml,
    parse_multistatus_xml,
)


def test_strip_ns() -> None:
    """Test Clark notation namespace stripping."""
    assert strip_ns("{DAV:}href") == "href"
    assert strip_ns("href") == "href"
    assert strip_ns("{urn:ietf:params:xml:ns:caldav}calendar") == "calendar"


def test_build_propfind_xml(snapshot: SnapshotAssertion) -> None:
    """Test generating <d:propfind> XML payload bytes against snapshot."""
    xml_bytes = build_propfind_xml(["resourcetype", "getetag", "displayname"])
    assert xml_bytes.decode("utf-8") == snapshot


def test_parse_multistatus_xml(snapshot: SnapshotAssertion) -> None:
    """Test parsing a WebDAV <DAV:multistatus> XML response against snapshot."""
    sample_xml = b"""<?xml version="1.0" encoding="utf-8"?>
<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
    <d:response>
        <d:href>/calendars/work/</d:href>
        <d:propstat>
            <d:prop>
                <d:resourcetype>
                    <d:collection/>
                    <c:calendar/>
                </d:resourcetype>
                <d:displayname>Work Calendar</d:displayname>
            </d:prop>
            <d:status>HTTP/1.1 200 OK</d:status>
        </d:propstat>
    </d:response>
    <d:response>
        <d:href>/calendars/work/event1.ics</d:href>
        <d:propstat>
            <d:prop>
                <d:resourcetype/>
                <d:getetag>"etag-123"</d:getetag>
            </d:prop>
            <d:status>HTTP/1.1 200 OK</d:status>
        </d:propstat>
    </d:response>
</d:multistatus>
"""
    items = parse_multistatus_xml(sample_xml)
    assert items == snapshot
