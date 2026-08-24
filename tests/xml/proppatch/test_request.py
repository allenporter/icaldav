"""Unit tests for PROPPATCH XML request parsing and building."""

import pytest

from icaldav.store.types import PropertyTag
from icaldav.xml.namespaces import DAV
from icaldav.xml.proppatch.request import build_proppatch_xml, parse_proppatch_request


def test_build_and_parse_proppatch_set_and_remove() -> None:
    """Test round-trip building and parsing of <DAV:propertyupdate>."""
    tag_name = PropertyTag(DAV, "displayname")
    tag_custom = PropertyTag("http://example.com/ns", "custom-prop")
    tag_remove = PropertyTag("http://example.com/ns", "old-prop")

    xml_bytes = build_proppatch_xml(
        set_props={tag_name: "My Calendar", tag_custom: "value123"},
        remove_props=[tag_remove],
    )
    assert b"<d:propertyupdate" in xml_bytes or b"<propertyupdate" in xml_bytes

    set_props, remove_props = parse_proppatch_request(xml_bytes)
    assert set_props[tag_name] == "My Calendar"
    assert set_props[tag_custom] == "value123"
    assert tag_remove in remove_props


def test_parse_invalid_proppatch_request() -> None:
    """Test error handling on invalid XML payloads."""
    with pytest.raises(ValueError, match="Invalid XML"):
        parse_proppatch_request(b"<unclosed>")

    with pytest.raises(ValueError, match="Expected root tag"):
        parse_proppatch_request(b"<notpropupdate/>")

    empty_set, empty_rem = parse_proppatch_request(b"")
    assert empty_set == {}
    assert empty_rem == []
