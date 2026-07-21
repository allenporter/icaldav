"""Unit tests for PROPFIND XML request generation and parsing."""

from syrupy.assertion import SnapshotAssertion

from icaldav.xml.namespaces import CALDAV, DAV
from icaldav.xml.propfind.request import (
    build_propfind_xml,
    parse_propfind_request,
)


def test_build_propfind_xml(snapshot: SnapshotAssertion) -> None:
    """Test generating <d:propfind> XML payload bytes against snapshot."""
    xml_bytes = build_propfind_xml(["resourcetype", "getetag", "displayname"])
    assert xml_bytes.decode("utf-8") == snapshot


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
