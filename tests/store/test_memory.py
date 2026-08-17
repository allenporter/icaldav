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


@pytest.mark.asyncio
async def test_memory_store_get_changes_since() -> None:
    """Test delta sync changes and tombstone tracking in MemoryStore."""
    store = MemoryStore()

    changes0 = await store.get_changes_since("/work", sync_token=None)
    assert len(changes0.changed) == 0
    token0 = changes0.sync_token

    await store.save_resource(
        CalendarResource(
            path=ResourcePath.parse("/work/event1.ics"),
            etag="etag-1",
            ics_data=SAMPLE_ICS_DATA,
            uid="123",
        )
    )

    changes1 = await store.get_changes_since("/work", sync_token=token0)
    assert len(changes1.changed) == 1
    assert changes1.deleted_hrefs == []
    token1 = changes1.sync_token

    await store.delete_resource("/work/event1.ics")

    changes2 = await store.get_changes_since("/work", sync_token=token1)
    assert len(changes2.changed) == 0
    assert changes2.deleted_hrefs == ["/work/event1.ics"]
