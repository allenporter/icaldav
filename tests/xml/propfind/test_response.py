"""Unit tests for PROPFIND Multi-Status XML response parsing."""

import xml.etree.ElementTree as ET

import pytest
from syrupy.assertion import SnapshotAssertion

from icaldav.xml.propfind.response import parse_multistatus_xml

# Billion Laughs (exponential entity expansion) attack payload.
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
    """Verify that Python's expat (>=2.4.1) rejects the Billion Laughs entity expansion bomb."""
    with pytest.raises(ET.ParseError):
        ET.fromstring(BILLION_LAUGHS_XML)


def test_parse_multistatus_billion_laughs_returns_empty() -> None:
    """Verify parse_multistatus_xml gracefully handles a Billion Laughs payload."""
    items = parse_multistatus_xml(BILLION_LAUGHS_XML)
    assert items == []


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
    assert items[0].propstats[0].status_code == 200


def test_create_property_element_supported_components() -> None:
    """Test create_property_element for supported-calendar-component-set."""
    from icaldav.xml.namespaces import CALDAV, CalDavProp
    from icaldav.xml.propfind.response import create_property_element

    sccs = create_property_element(
        CALDAV,
        CalDavProp.SUPPORTED_CALENDAR_COMPONENT_SET,
        "/work/",
        is_collection=True,
    )
    assert sccs is not None
    comps = [child.attrib.get("name") for child in sccs]
    assert comps == ["VEVENT", "VTODO", "VJOURNAL"]

    # Non-collection returns None
    sccs_file = create_property_element(
        CALDAV,
        CalDavProp.SUPPORTED_CALENDAR_COMPONENT_SET,
        "/work/event.ics",
        is_collection=False,
    )
    assert sccs_file is None
