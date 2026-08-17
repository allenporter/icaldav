"""Unit and integration tests for SQLiteStore persistence and delta sync."""

from pathlib import Path

import pytest

from icaldav.store.sqlite import SQLiteStore
from icaldav.store.types import CalendarResource, CollectionPath, ResourcePath

SAMPLE_ICS_1 = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Example Corp.//EN
BEGIN:VEVENT
UID:123
SUMMARY:Test Meeting 1
END:VEVENT
END:VCALENDAR"""

SAMPLE_ICS_2 = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Example Corp.//EN
BEGIN:VEVENT
UID:456
SUMMARY:Test Meeting 2
END:VEVENT
END:VCALENDAR"""


@pytest.mark.asyncio
async def test_sqlite_store_sync_token() -> None:
    """Test sync token management in SQLiteStore."""
    store = SQLiteStore(":memory:")

    assert await store.get_sync_token("/work") is None

    await store.set_sync_token("/work", "data:,5")
    assert await store.get_sync_token("/work") == "data:,5"
    await store.close()


@pytest.mark.asyncio
async def test_sqlite_store_resource_crud() -> None:
    """Test saving, retrieving, listing, and deleting resources in SQLiteStore."""
    store = SQLiteStore(":memory:")

    assert await store.get_resource("/work/event1.ics") is None
    assert await store.collection_exists("/work") is False

    await store.create_collection("/work")
    assert await store.collection_exists("/work") is True

    res1 = CalendarResource(
        path=ResourcePath.parse("/work/event1.ics"),
        etag="etag-1",
        ics_data=SAMPLE_ICS_1,
        uid="123",
    )
    await store.save_resource(res1)

    fetched = await store.get_resource("/work/event1.ics")
    assert fetched is not None
    assert fetched.path.canonical == "/work/event1.ics"
    assert fetched.etag == "etag-1"
    assert fetched.ics_data == SAMPLE_ICS_1
    assert fetched.uid == "123"

    etags = await store.get_etags("/work")
    assert etags == {"/work/event1.ics": "etag-1"}

    all_res = await store.get_resources("/work")
    assert len(all_res) == 1
    assert all_res[0].path.canonical == "/work/event1.ics"

    deleted = await store.delete_resource("/work/event1.ics")
    assert deleted is True
    assert await store.get_resource("/work/event1.ics") is None
    assert await store.delete_resource("/work/event1.ics") is False
    await store.close()


@pytest.mark.asyncio
async def test_sqlite_store_get_changes_since_and_tombstones() -> None:
    """Test delta sync changes and tombstone tracking."""
    store = SQLiteStore(":memory:")
    coll = CollectionPath.parse("/work")

    # Initial sync on empty collection
    init_changes = await store.get_changes_since(coll, sync_token=None)
    assert init_changes.changed == []
    assert init_changes.deleted_hrefs == []
    token_0 = init_changes.sync_token

    # Add event1
    await store.save_resource(
        CalendarResource(
            path=ResourcePath.parse("/work/event1.ics"),
            etag="etag-1",
            ics_data=SAMPLE_ICS_1,
            uid="123",
        )
    )

    # Add event2
    await store.save_resource(
        CalendarResource(
            path=ResourcePath.parse("/work/event2.ics"),
            etag="etag-2",
            ics_data=SAMPLE_ICS_2,
            uid="456",
        )
    )

    # Sync since token_0 should return both events
    changes_1 = await store.get_changes_since(coll, sync_token=token_0)
    assert len(changes_1.changed) == 2
    assert changes_1.deleted_hrefs == []
    token_1 = changes_1.sync_token

    # Delete event1
    await store.delete_resource("/work/event1.ics")

    # Sync since token_1 should return event1 in deleted_hrefs
    changes_2 = await store.get_changes_since(coll, sync_token=token_1)
    assert len(changes_2.changed) == 0
    assert changes_2.deleted_hrefs == ["/work/event1.ics"]
    token_2 = changes_2.sync_token

    # Sync since token_2 should return nothing
    changes_3 = await store.get_changes_since(coll, sync_token=token_2)
    assert len(changes_3.changed) == 0
    assert len(changes_3.deleted_hrefs) == 0
    await store.close()


@pytest.mark.asyncio
async def test_sqlite_store_persistence(tmp_path: Path) -> None:
    """Test data persistence across SQLiteStore instances with disk database."""
    db_file = tmp_path / "test_calendar.db"

    # Store 1: write resource
    store1 = SQLiteStore(db_file)
    await store1.create_collection("/work")
    await store1.save_resource(
        CalendarResource(
            path=ResourcePath.parse("/work/persisted.ics"),
            etag="etag-persisted",
            ics_data=SAMPLE_ICS_1,
            uid="123",
        )
    )
    await store1.close()

    # Store 2: reopen and verify content
    store2 = SQLiteStore(db_file)
    res = await store2.get_resource("/work/persisted.ics")
    assert res is not None
    assert res.etag == "etag-persisted"
    assert res.ics_data == SAMPLE_ICS_1
    await store2.close()
