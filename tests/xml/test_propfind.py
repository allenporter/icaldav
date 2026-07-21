"""Unit tests for PROPFIND XML generation and multi-status parsing using syrupy snapshot testing."""

import xml.etree.ElementTree as ET

import pytest
from syrupy.assertion import SnapshotAssertion

from icaldav.xml.namespaces import CALDAV, DAV, strip_ns
from icaldav.xml.propfind.request import (
    build_propfind_xml,
    parse_propfind_request,
)
from icaldav.xml.propfind.response import parse_multistatus_xml


# Billion Laughs (exponential entity expansion) attack payload.
# Each level expands 10x, so &lol9; would expand to ~10^9 "lol" strings
# (~3GB) from a few hundred bytes of input.
BILLION_LAUGHS_XML = b"""\
<?xml version="1.0"?>
<!DOCTYPE lolz [
  <!ENTITY lol "lol">
  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
  <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
  <!ENTITY lol5 "&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;">
  <!ENTITY lol6 "&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;">
  <!ENTITY lol7 "&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;">
  <!ENTITY lol8 "&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;">
  <!ENTITY lol9 "&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;">
]>
<d:multistatus xmlns:d="DAV:">
  <d:response>
    <d:href>&lol9;</d:href>
  </d:response>
</d:multistatus>
"""


def test_strip_ns() -> None:
    """Test Clark notation namespace stripping."""
    assert strip_ns("{DAV:}href") == "href"
    assert strip_ns("href") == "href"
    assert strip_ns("{urn:ietf:params:xml:ns:caldav}calendar") == "calendar"


def test_build_propfind_xml(snapshot: SnapshotAssertion) -> None:
    """Test generating <d:propfind> XML payload bytes against snapshot."""
    xml_bytes = build_propfind_xml(["resourcetype", "getetag", "displayname"])
    assert xml_bytes.decode("utf-8") == snapshot


def test_parse_propfind_request() -> None:
    """Test parsing PROPFIND request XML bodies."""
    # Empty / no body
    assert parse_propfind_request(b"") is None

    # <allprop/> body
    allprop_xml = (
        b'<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:allprop/></d:propfind>'
    )
    assert parse_propfind_request(allprop_xml) is None

    # <prop> body with DAV and CalDAV properties
    prop_xml = b"""<?xml version="1.0"?>
<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
    <d:prop>
        <d:resourcetype/>
        <d:owner/>
        <c:calendar-home-set/>
    </d:prop>
</d:propfind>"""
    parsed = parse_propfind_request(prop_xml)
    assert parsed == [
        (DAV, "resourcetype"),
        (DAV, "owner"),
        (CALDAV, "calendar-home-set"),
    ]


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


def test_billion_laughs_rejected_by_parser() -> None:
    """Verify that Python's expat (>=2.4.1) rejects the Billion Laughs entity expansion bomb.

    This is a regression test ensuring the XML parser raises an error
    rather than consuming unbounded memory. Python >=3.11 bundles expat
    >=2.4.1 which blocks exponential entity expansion natively.
    """
    with pytest.raises(ET.ParseError):
        ET.fromstring(BILLION_LAUGHS_XML)


def test_parse_multistatus_billion_laughs_returns_empty() -> None:
    """Verify parse_multistatus_xml gracefully handles a Billion Laughs payload.

    The function should return an empty list rather than crash or hang,
    since the underlying ET.fromstring will reject the malicious XML.
    """
    items = parse_multistatus_xml(BILLION_LAUGHS_XML)
    assert items == []


def test_build_propfind_xml_allprop() -> None:
    """Test generating <d:propfind> with empty props list produces <allprop> element."""
    xml_bytes = build_propfind_xml(None)
    assert b"allprop" in xml_bytes

    xml_bytes_empty = build_propfind_xml([])
    assert b"allprop" in xml_bytes_empty


def test_build_propfind_xml_qualified_props() -> None:
    """Test generating <d:propfind> with Clark-notation namespace qualified properties."""
    props = ["{DAV:}displayname", "{urn:ietf:params:xml:ns:caldav}calendar-data"]
    xml_bytes = build_propfind_xml(props)
    assert b"displayname" in xml_bytes
    assert b"calendar-data" in xml_bytes


def test_parse_multistatus_xml_edge_cases() -> None:
    """Test parse_multistatus_xml with empty bytes, whitespace, and non-numeric status code."""
    assert parse_multistatus_xml(b"") == []
    assert parse_multistatus_xml(b"   \n  ") == []

    non_numeric_status_xml = b"""<?xml version="1.0" encoding="utf-8"?>
    <d:multistatus xmlns:d="DAV:">
        <d:response>
            <d:href>/work/test.ics</d:href>
            <d:propstat>
                <d:prop><d:getetag>abc</d:getetag></d:prop>
                <d:status>HTTP/1.1 INVALID_STATUS OK</d:status>
            </d:propstat>
        </d:response>
    </d:multistatus>
    """
    items = parse_multistatus_xml(non_numeric_status_xml)
    assert len(items) == 1
    # Fallback status code is 200
    assert items[0].propstats[0].status_code == 200
