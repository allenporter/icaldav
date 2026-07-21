"""Unit tests for WebDAV / CalDAV XML namespaces and helper functions."""

from icaldav.xml.namespaces import strip_ns


def test_strip_ns() -> None:
    """Test Clark notation namespace stripping."""
    assert strip_ns("{DAV:}href") == "href"
    assert strip_ns("href") == "href"
    assert strip_ns("{urn:ietf:params:xml:ns:caldav}calendar") == "calendar"
