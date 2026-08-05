"""Unit tests for MemoryStore."""

import pytest

from icaldav.store.memory import MemoryStore
from icaldav.store.types import CalendarResource, ResourcePath

SAMPLE_ICS_DATA = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Example Corp.//EN
BEGIN:VEVENT
UID:123
SUMMARY:Test Meeting
END:VEVENT
END:VCALENDAR"""


@pytest.mark.asyncio
async def test_memory_store_sync_token() -> None:
    """Test setting and getting sync tokens in MemoryStore."""
    store = MemoryStore()

    assert await store.get_sync_token("/work") is None

    await store.set_sync_token("/work", "token-123")
    assert await store.get_sync_token("/work") == "token-123"


@pytest.mark.asyncio
async def test_memory_store_resource_crud() -> None:
    """Test saving, retrieving, etag listing, and deleting resources in MemoryStore."""
    store = MemoryStore()

    res = await store.get_resource("/work/event1.ics")
    assert res is None

    resource = CalendarResource(
        path=ResourcePath.parse("/work/event1.ics"),
        etag="etag-1",
        ics_data=SAMPLE_ICS_DATA,
        uid="123",
    )
    await store.save_resource(resource)

    res = await store.get_resource("/work/event1.ics")
    assert res is not None
    assert res.href == "/work/event1.ics"
    assert res.etag == "etag-1"
    assert res.ics_data == SAMPLE_ICS_DATA
    assert res.uid == "123"

    etags = await store.get_etags("/work")
    assert etags == {"/work/event1.ics": "etag-1"}

    deleted = await store.delete_resource("/work/event1.ics")
    assert deleted is True

    assert await store.get_resource("/work/event1.ics") is None
    assert await store.get_etags("/work") == {}

    # Deleting non-existent resource returns False
    assert await store.delete_resource("/work/event1.ics") is False
