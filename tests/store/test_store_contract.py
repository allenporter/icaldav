"""Shared LocalStore contract test suite verifying MemoryStore and SQLiteStore parity."""

from collections.abc import AsyncGenerator

import pytest

from icaldav.store.memory import MemoryStore
from icaldav.store.sqlite import SQLiteStore
from icaldav.store.types import (
    CalendarResource,
    CollectionPath,
    LocalStore,
    ResourcePath,
)

SAMPLE_ICS_1 = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Example Corp.//EN
BEGIN:VEVENT
UID:event-1
SUMMARY:Meeting 1
END:VEVENT
END:VCALENDAR"""

SAMPLE_ICS_2 = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Example Corp.//EN
BEGIN:VEVENT
UID:event-2
SUMMARY:Meeting 2
END:VEVENT
END:VCALENDAR"""


@pytest.fixture(params=["memory", "sqlite"])
async def store(request: pytest.FixtureRequest) -> AsyncGenerator[LocalStore]:
    """Yield freshly initialized LocalStore instances for each backend."""
    if request.param == "memory":
        yield MemoryStore()
    elif request.param == "sqlite":
        sqlite_store = SQLiteStore(":memory:")
        try:
            yield sqlite_store
        finally:
            await sqlite_store.close()
    else:
        raise ValueError(f"Unknown store backend: {request.param}")


@pytest.mark.asyncio
async def test_store_collection_lifecycle(store: LocalStore) -> None:
    """Verify collection existence and creation across store implementations."""
    coll = CollectionPath.parse("/work")
    assert await store.collection_exists(coll) is False

    await store.create_collection(coll)
    assert await store.collection_exists(coll) is True


@pytest.mark.asyncio
async def test_store_sync_token_management(store: LocalStore) -> None:
    """Verify sync token setting and retrieval across store implementations."""
    coll = CollectionPath.parse("/work")
    assert await store.get_sync_token(coll) is None

    await store.set_sync_token(coll, "data:,5")
    token = await store.get_sync_token(coll)
    assert token is not None
    assert "5" in token


@pytest.mark.asyncio
async def test_store_resource_crud(store: LocalStore) -> None:
    """Verify complete CRUD lifecycle across store implementations."""
    res_path = ResourcePath.parse("/work/event1.ics")
    assert await store.get_resource(res_path) is None

    resource = CalendarResource(
        path=res_path,
        etag="etag-123",
        ics_data=SAMPLE_ICS_1,
        uid="event-1",
    )
    await store.save_resource(resource)

    fetched = await store.get_resource(res_path)
    assert fetched is not None
    assert fetched.path.canonical == "/work/event1.ics"
    assert fetched.etag == "etag-123"
    assert fetched.ics_data == SAMPLE_ICS_1
    assert fetched.uid == "event-1"

    coll = CollectionPath.parse("/work")
    etags = await store.get_etags(coll)
    assert etags == {"/work/event1.ics": "etag-123"}

    all_res = await store.get_resources(coll)
    assert len(all_res) == 1
    assert all_res[0].path.canonical == "/work/event1.ics"

    # Delete existing returns True
    assert await store.delete_resource(res_path) is True
    assert await store.get_resource(res_path) is None
    assert await store.get_etags(coll) == {}

    # Delete non-existent returns False
    assert await store.delete_resource(res_path) is False


@pytest.mark.asyncio
async def test_store_get_changes_since_and_tombstones(store: LocalStore) -> None:
    """Verify initial sync, delta sync, tombstones, and limits across store implementations."""
    coll = CollectionPath.parse("/work")

    # 1. Initial sync on empty collection
    init_changes = await store.get_changes_since(coll, sync_token=None)
    assert init_changes.changed == []
    assert init_changes.deleted_hrefs == []
    assert init_changes.has_more is False
    token_0 = init_changes.sync_token

    # 2. Add two resources
    event1_path = ResourcePath.parse("/work/event1.ics")
    event2_path = ResourcePath.parse("/work/event2.ics")
    await store.save_resource(
        CalendarResource(
            path=event1_path,
            etag="etag-1",
            ics_data=SAMPLE_ICS_1,
            uid="event-1",
        )
    )
    await store.save_resource(
        CalendarResource(
            path=event2_path,
            etag="etag-2",
            ics_data=SAMPLE_ICS_2,
            uid="event-2",
        )
    )

    # 3. Delta sync since token_0 returns both new events
    changes_1 = await store.get_changes_since(coll, sync_token=token_0)
    assert len(changes_1.changed) == 2
    assert changes_1.deleted_hrefs == []
    token_1 = changes_1.sync_token

    # 4. Limit testing
    limited = await store.get_changes_since(coll, sync_token=token_0, limit=1)
    assert len(limited.changed) == 1
    assert limited.has_more is True

    # 5. Delete event1
    assert await store.delete_resource(event1_path) is True

    # 6. Delta sync since token_1 returns event1 as tombstone
    changes_2 = await store.get_changes_since(coll, sync_token=token_1)
    assert len(changes_2.changed) == 0
    assert changes_2.deleted_hrefs == ["/work/event1.ics"]
    token_2 = changes_2.sync_token

    # 7. Delta sync since token_2 returns no modifications
    changes_3 = await store.get_changes_since(coll, sync_token=token_2)
    assert len(changes_3.changed) == 0
    assert len(changes_3.deleted_hrefs) == 0


@pytest.mark.asyncio
async def test_store_multipage_sync_pagination(store: LocalStore) -> None:
    """RFC 6578 §3.7: Verify multi-page sync token iteration for initial and delta sync."""
    coll = CollectionPath.parse("/work")
    await store.create_collection(coll)

    # 1. Add 4 resources
    for i in range(1, 5):
        await store.save_resource(
            CalendarResource(
                path=ResourcePath.parse(f"/work/event{i}.ics"),
                etag=f"etag-{i}",
                ics_data=f"BEGIN:VCALENDAR\nUID:event-{i}\nEND:VCALENDAR",
                uid=f"event-{i}",
            )
        )

    # 2. Initial sync pagination with limit=2
    page1 = await store.get_changes_since(coll, sync_token=None, limit=2)
    assert len(page1.changed) == 2
    assert page1.deleted_hrefs == []
    assert page1.has_more is True
    token_p1 = page1.sync_token

    page2 = await store.get_changes_since(coll, sync_token=token_p1, limit=2)
    assert len(page2.changed) == 2
    assert page2.deleted_hrefs == []
    assert page2.has_more is False
    token_p2 = page2.sync_token

    # Verify all 4 resources were returned across pages
    all_hrefs = [r.path.canonical for r in page1.changed + page2.changed]
    assert all_hrefs == [f"/work/event{i}.ics" for i in range(1, 5)]

    # 3. Delta changes: modify 1, delete 1, add 1 (3 total delta changes)
    await store.save_resource(
        CalendarResource(
            path=ResourcePath.parse("/work/event1.ics"),
            etag="etag-1-updated",
            ics_data="BEGIN:VCALENDAR\nUID:event-1\nSUMMARY:Updated\nEND:VCALENDAR",
            uid="event-1",
        )
    )
    await store.delete_resource(ResourcePath.parse("/work/event2.ics"))
    await store.save_resource(
        CalendarResource(
            path=ResourcePath.parse("/work/event5.ics"),
            etag="etag-5",
            ics_data="BEGIN:VCALENDAR\nUID:event-5\nEND:VCALENDAR",
            uid="event-5",
        )
    )

    # 4. Delta sync pagination with limit=2
    d_page1 = await store.get_changes_since(coll, sync_token=token_p2, limit=2)
    assert len(d_page1.changed) + len(d_page1.deleted_hrefs) == 2
    assert d_page1.has_more is True
    token_dp1 = d_page1.sync_token

    d_page2 = await store.get_changes_since(coll, sync_token=token_dp1, limit=2)
    assert len(d_page2.changed) + len(d_page2.deleted_hrefs) == 1
    assert d_page2.has_more is False
    token_dp2 = d_page2.sync_token

    # Verify delta changes across pages
    all_d_changed = [r.path.canonical for r in d_page1.changed + d_page2.changed]
    all_d_deleted = d_page1.deleted_hrefs + d_page2.deleted_hrefs
    assert set(all_d_changed) == {"/work/event1.ics", "/work/event5.ics"}
    assert all_d_deleted == ["/work/event2.ics"]

    # 5. Delta sync with final token returns no changes
    d_page3 = await store.get_changes_since(coll, sync_token=token_dp2, limit=2)
    assert d_page3.changed == []
    assert d_page3.deleted_hrefs == []
    assert d_page3.has_more is False
