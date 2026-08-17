"""Unit tests for PROPFIND Multi-Status XML response parsing."""

import xml.etree.ElementTree as ET

import pytest
from syrupy.assertion import SnapshotAssertion

from icaldav.store.principal import PrincipalInfo
from icaldav.store.types import ResourceKind, ResourceTarget
from icaldav.xml.namespaces import (
    CALDAV,
    CALSERVER,
    DAV,
    CalDavProp,
    CalServerProp,
    DavProp,
    strip_ns,
)
from icaldav.xml.propfind.response import (
    create_property_element,
    parse_multistatus_xml,
)

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
    cal_target = ResourceTarget(href="/work/", kind=ResourceKind.CALENDAR)
    sccs = create_property_element(
        CALDAV,
        CalDavProp.SUPPORTED_CALENDAR_COMPONENT_SET,
        cal_target,
    )
    assert sccs is not None
    comps = [child.attrib.get("name") for child in sccs]
    assert comps == ["VEVENT", "VTODO", "VJOURNAL"]

    # Non-collection returns None
    res_target = ResourceTarget(href="/work/event.ics", kind=ResourceKind.RESOURCE)
    sccs_file = create_property_element(
        CALDAV,
        CalDavProp.SUPPORTED_CALENDAR_COMPONENT_SET,
        res_target,
    )
    assert sccs_file is None


def test_create_property_element_resourcetype_variants() -> None:
    """Test resourcetype generation for principal, root, and calendar collections."""
    # Principal resource -> <collection/><principal/>
    p_target = ResourceTarget(href="/principals/user/", kind=ResourceKind.PRINCIPAL)
    p_rt = create_property_element(DAV, DavProp.RESOURCETYPE, p_target)
    assert p_rt is not None
    p_tags = [strip_ns(child.tag) for child in p_rt]
    assert p_tags == ["collection", "principal"]

    # Root collection -> <collection/>
    r_target = ResourceTarget(href="/", kind=ResourceKind.ROOT)
    r_rt = create_property_element(DAV, DavProp.RESOURCETYPE, r_target)
    assert r_rt is not None
    r_tags = [strip_ns(child.tag) for child in r_rt]
    assert r_tags == ["collection"]

    # Calendar collection -> <collection/><calendar/>
    c_target = ResourceTarget(href="/work/", kind=ResourceKind.CALENDAR)
    c_rt = create_property_element(DAV, DavProp.RESOURCETYPE, c_target)
    assert c_rt is not None
    c_tags = [strip_ns(child.tag) for child in c_rt]
    assert c_tags == ["collection", "calendar"]


def test_create_property_element_owner_and_getctag() -> None:
    """Test DAV:owner and CALSERVER:getctag property generation."""
    bernard = PrincipalInfo(
        user_id="bernard",
        principal_path="/principals/users/bernard/",
        calendar_home_path="/calendars/bernard/",
        email="mailto:bernard@example.com",
    )
    target = ResourceTarget(
        href="/work/",
        kind=ResourceKind.CALENDAR,
        ctag='"ctag-abc"',
        principal=bernard,
    )

    owner_elem = create_property_element(DAV, DavProp.OWNER, target)
    assert owner_elem is not None
    owner_href = owner_elem.find(f"{{{DAV}}}href")
    assert owner_href is not None
    assert owner_href.text == "/principals/users/bernard/"

    ctag_elem = create_property_element(CALSERVER, CalServerProp.GETCTAG, target)
    assert ctag_elem is not None
    assert ctag_elem.text == '"ctag-abc"'


def test_create_property_element_privileges_and_max_size() -> None:
    """Test DAV:current-user-privilege-set and CALDAV:max-resource-size property generation."""
    target = ResourceTarget(href="/work/", kind=ResourceKind.CALENDAR)

    cups_elem = create_property_element(DAV, DavProp.CURRENT_USER_PRIVILEGE_SET, target)
    assert cups_elem is not None
    priv_elem = cups_elem.find(f"{{{DAV}}}privilege")
    assert priv_elem is not None
    priv_tags = [strip_ns(child.tag) for child in priv_elem]
    assert "read" in priv_tags
    assert "write" in priv_tags
    assert "all" in priv_tags

    mrs_elem = create_property_element(CALDAV, CalDavProp.MAX_RESOURCE_SIZE, target)
    assert mrs_elem is not None
    assert mrs_elem.text == "10485760"


def test_create_property_element_supported_report_set() -> None:
    """Test DAV:supported-report-set property generation."""
    cal_target = ResourceTarget(href="/work/", kind=ResourceKind.CALENDAR)
    srs_elem = create_property_element(DAV, DavProp.SUPPORTED_REPORT_SET, cal_target)
    assert srs_elem is not None
    reports: list[str] = []
    for sr in srs_elem:
        rep = sr.find(f"{{{DAV}}}report")
        if rep is not None:
            for r_child in rep:
                reports.append(strip_ns(r_child.tag))
    assert "calendar-query" in reports
    assert "calendar-multiget" in reports

    # Non-calendar returns None
    res_target = ResourceTarget(href="/work/event.ics", kind=ResourceKind.RESOURCE)
    assert (
        create_property_element(DAV, DavProp.SUPPORTED_REPORT_SET, res_target) is None
    )


def test_create_property_element_sync_token() -> None:
    """Test DAV:sync-token property generation for calendar collections."""
    cal_target = ResourceTarget(
        href="/work/",
        kind=ResourceKind.CALENDAR,
        sync_token="http://icaldav.org/ns/sync-tokens/123",
    )
    st_elem = create_property_element(DAV, DavProp.SYNC_TOKEN, cal_target)
    assert st_elem is not None
    assert st_elem.text == "http://icaldav.org/ns/sync-tokens/123"

    res_target = ResourceTarget(href="/work/event.ics", kind=ResourceKind.RESOURCE)
    assert create_property_element(DAV, DavProp.SYNC_TOKEN, res_target) is None
