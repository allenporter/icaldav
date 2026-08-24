"""Unit tests for PROPPATCH XML response building and parsing."""

from icaldav.store.types import PropertyTag
from icaldav.xml.namespaces import DAV
from icaldav.xml.proppatch.response import (
    build_proppatch_response_xml,
    parse_proppatch_response,
)


def test_build_and_parse_successful_proppatch_response() -> None:
    """Test 200 OK Multi-Status PROPPATCH response."""
    tag1 = PropertyTag(DAV, "displayname")
    tag2 = PropertyTag("http://example.com/ns", "custom")

    xml_bytes = build_proppatch_response_xml("/work/", [tag1, tag2])
    assert b"200 OK" in xml_bytes

    parsed = parse_proppatch_response(xml_bytes)
    assert parsed[tag1] == 200
    assert parsed[tag2] == 200


def test_build_and_parse_failed_proppatch_response() -> None:
    """Test atomic failure (403 Forbidden + 424 Failed Dependency) response."""
    tag_protected = PropertyTag(DAV, "getetag")
    tag_ok = PropertyTag(DAV, "displayname")

    xml_bytes = build_proppatch_response_xml(
        "/work/event.ics",
        ok_props=[tag_ok],
        failed_props={tag_protected: 403},
    )
    assert b"403 Forbidden" in xml_bytes
    assert b"424 Failed Dependency" in xml_bytes

    parsed = parse_proppatch_response(xml_bytes)
    assert parsed[tag_protected] == 403
    assert parsed[tag_ok] == 424
