"""Unit tests for storage data structures and PropfindItem properties."""

from icaldav.store.types import (
    CalendarResource,
    CollectionPath,
    ResourcePath,
    SyncToken,
)
from icaldav.xml.propfind.models import PropfindItem, Propstat


def test_calendar_resource_creation() -> None:
    """Test CalendarResource attributes and defaults."""
    res = CalendarResource(
        path=ResourcePath.parse("/work/event1.ics"),
        etag="etag123",
        ics_data="BEGIN:VCALENDAR\r\nEND:VCALENDAR",
    )
    assert res.href == "/work/event1.ics"
    assert res.path.canonical == "/work/event1.ics"
    assert res.path.collection_path == CollectionPath.parse("/work")
    assert res.path.filename == "event1.ics"
    assert res.etag == "etag123"
    assert res.ics_data == "BEGIN:VCALENDAR\r\nEND:VCALENDAR"
    assert res.uid is None

    res_with_uid = CalendarResource(
        path=ResourcePath.parse("/work/event2.ics"),
        etag="etag456",
        ics_data="BEGIN:VCALENDAR\r\nEND:VCALENDAR",
        uid="uid-123",
    )
    assert res_with_uid.uid == "uid-123"


def test_propfind_item_properties() -> None:
    """Test PropfindItem properties for collection, calendar, and etag."""
    # Empty item
    item_empty = PropfindItem(href="/work/")
    assert item_empty.is_collection is False
    assert item_empty.is_calendar is False
    assert item_empty.etag is None

    # Collection & Calendar item
    item_cal = PropfindItem(
        href="/work/",
        propstats=[
            Propstat(
                status_code=200,
                properties={"is_collection": True, "is_calendar": True},
            )
        ],
    )
    assert item_cal.is_collection is True
    assert item_cal.is_calendar is True
    assert item_cal.etag is None

    # File resource item with etag
    item_file = PropfindItem(
        href="/work/event1.ics",
        propstats=[
            Propstat(
                status_code=200,
                properties={"getetag": '"etag-abc"'},
            )
        ],
    )
    assert item_file.is_collection is False
    assert item_file.is_calendar is False
    assert item_file.etag == '"etag-abc"'

    # Non-200 propstat should be ignored by helper properties
    item_404 = PropfindItem(
        href="/work/missing.ics",
        propstats=[
            Propstat(
                status_code=404,
                properties={
                    "is_collection": True,
                    "is_calendar": True,
                    "getetag": '"etag-xyz"',
                },
            )
        ],
    )
    assert item_404.is_collection is False
    assert item_404.is_calendar is False
    assert item_404.etag is None


def test_sync_token_parsing_and_formatting() -> None:
    """Test SyncToken parsing, sequence extraction, and formatting."""
    t_init = SyncToken.initial()
    assert t_init.sequence == 0
    assert t_init.uri == "data:,0"
    assert t_init.is_initial is True

    t_next = t_init.next()
    assert t_next.sequence == 1
    assert t_next.uri == "data:,1"
    assert t_next.is_initial is False

    t_from_str = SyncToken.parse("data:,42")
    assert t_from_str.sequence == 42
    assert t_from_str.uri == "data:,42"

    t_opaque = SyncToken.parse("http://example.com/sync/99")
    assert t_opaque.sequence == 99
    assert t_opaque.uri == "http://example.com/sync/99"

    t_none = SyncToken.parse(None)
    assert t_none.sequence == 0
    assert t_none.is_initial is True
