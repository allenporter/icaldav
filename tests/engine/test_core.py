"""Unit tests for the CoreWebDavEngine domain logic."""

import pytest

from icaldav.engine.core import CALDAV, CALSERVER, DAV, CoreWebDavEngine
from icaldav.engine.models import (
    CalendarMultigetQuery,
    CalendarQuery,
    PrincipalSearchQuery,
    PropertyTag,
    PropfindQuery,
    SearchCriteria,
    SyncCollectionQuery,
)
from icaldav.filter import CompFilter
from icaldav.store.memory import MemoryStore
from icaldav.store.principal import InMemoryPrincipalStore, PrincipalInfo
from icaldav.store.types import CalendarResource, CollectionPath, ResourcePath

SAMPLE_VEVENT = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:evt-1
DTSTART:20260810T100000Z
DTEND:20260810T110000Z
SUMMARY:Meeting 1
END:VEVENT
END:VCALENDAR"""


@pytest.mark.asyncio
async def test_evaluate_propfind_root() -> None:
    """Test PROPFIND on the root path."""
    engine = CoreWebDavEngine()
    store = MemoryStore()
    p_store = InMemoryPrincipalStore()

    query = PropfindQuery(
        href="/",
        depth=0,
        requested_props=None,
        user_id="user",
    )
    result = await engine.evaluate_propfind(store, p_store, query)
    assert len(result.responses) == 1
    resp = result.responses[0]
    assert resp.href == "/"
    # Root should have 200 OK propstat block
    ok_block = next(b for b in resp.propstats if b.status_code == 200)
    assert PropertyTag(DAV, "resourcetype") in ok_block.properties
    assert ok_block.properties[PropertyTag(DAV, "resourcetype")] == ["collection"]


@pytest.mark.asyncio
async def test_evaluate_propfind_principal() -> None:
    """Test PROPFIND on a principal path with display_name set."""
    engine = CoreWebDavEngine()
    store = MemoryStore()
    p_store = InMemoryPrincipalStore(
        principals=[
            PrincipalInfo(
                user_id="user",
                principal_path="/principals/user/",
                calendar_home_path="/",
                email="mailto:user@localhost",
                display_name="User Display Name",
            )
        ]
    )

    query = PropfindQuery(
        href="/principals/user/",
        depth=0,
        requested_props=[
            PropertyTag(DAV, "resourcetype"),
            PropertyTag(DAV, "displayname"),
            PropertyTag(DAV, "nonexistent"),
        ],
        user_id="user",
    )
    result = await engine.evaluate_propfind(store, p_store, query)
    assert len(result.responses) == 1
    resp = result.responses[0]
    assert resp.href == "/principals/user/"

    ok_block = next(b for b in resp.propstats if b.status_code == 200)
    assert ok_block.properties[PropertyTag(DAV, "resourcetype")] == [
        "collection",
        "principal",
    ]
    assert ok_block.properties[PropertyTag(DAV, "displayname")] == "User Display Name"

    err_block = next(b for b in resp.propstats if b.status_code == 404)
    assert PropertyTag(DAV, "nonexistent") in err_block.properties


@pytest.mark.asyncio
async def test_evaluate_propfind_principal_without_displayname() -> None:
    """Test PROPFIND on a principal path where display_name is not set (404 for displayname)."""
    engine = CoreWebDavEngine()
    store = MemoryStore()
    p_store = InMemoryPrincipalStore(
        principals=[
            PrincipalInfo(
                user_id="user",
                principal_path="/principals/user/",
                calendar_home_path="/",
                email="mailto:user@localhost",
                display_name=None,
            )
        ]
    )

    query = PropfindQuery(
        href="/principals/user/",
        depth=0,
        requested_props=[
            PropertyTag(DAV, "resourcetype"),
            PropertyTag(DAV, "displayname"),
        ],
        user_id="user",
    )
    result = await engine.evaluate_propfind(store, p_store, query)
    assert len(result.responses) == 1
    resp = result.responses[0]

    ok_block = next(b for b in resp.propstats if b.status_code == 200)
    assert ok_block.properties[PropertyTag(DAV, "resourcetype")] == [
        "collection",
        "principal",
    ]
    assert PropertyTag(DAV, "displayname") not in ok_block.properties

    err_block = next(b for b in resp.propstats if b.status_code == 404)
    assert PropertyTag(DAV, "displayname") in err_block.properties


@pytest.mark.asyncio
async def test_evaluate_propfind_calendar_collection() -> None:
    """Test PROPFIND on a calendar collection collection."""
    engine = CoreWebDavEngine()
    store = MemoryStore()
    p_store = InMemoryPrincipalStore()

    await store.create_collection("/work")

    # Add a resource in the collection
    res = CalendarResource(
        path=ResourcePath.parse("/work/event1.ics"),
        etag="etag-123",
        ics_data=SAMPLE_VEVENT,
    )
    await store.save_resource(res)
    await store.set_sync_token("/work", "token-123")

    # 1. Depth = 0 (only collection)
    query_d0 = PropfindQuery(
        href="/work/",
        depth=0,
        requested_props=None,
        user_id="user",
    )
    result_d0 = await engine.evaluate_propfind(store, p_store, query_d0)
    assert len(result_d0.responses) == 1
    assert result_d0.responses[0].href == "/work/"
    ok_block = next(b for b in result_d0.responses[0].propstats if b.status_code == 200)
    assert ok_block.properties[PropertyTag(DAV, "sync-token")] == "token-123"
    assert ok_block.properties[
        PropertyTag(CALSERVER, "getctag")
    ] == '"ctag-abc"' or ok_block.properties[
        PropertyTag(CALSERVER, "getctag")
    ].startswith('"ctag-')

    # 2. Depth = 1 (collection + child resources)
    query_d1 = PropfindQuery(
        href="/work/",
        depth=1,
        requested_props=[
            PropertyTag(DAV, "getetag"),
            PropertyTag(DAV, "resourcetype"),
        ],
        user_id="user",
    )
    result_d1 = await engine.evaluate_propfind(store, p_store, query_d1)
    assert len(result_d1.responses) == 2
    # First response: collection
    assert result_d1.responses[0].href == "/work/"
    # Second response: resource
    assert result_d1.responses[1].href == "/work/event1.ics"
    res_ok = next(b for b in result_d1.responses[1].propstats if b.status_code == 200)
    assert res_ok.properties[PropertyTag(DAV, "getetag")] == "etag-123"
    assert res_ok.properties[PropertyTag(DAV, "resourcetype")] == []


@pytest.mark.asyncio
async def test_evaluate_propfind_resource() -> None:
    """Test PROPFIND on a single resource."""
    engine = CoreWebDavEngine()
    store = MemoryStore()
    p_store = InMemoryPrincipalStore()

    await store.create_collection("/work")
    res = CalendarResource(
        path=ResourcePath.parse("/work/event1.ics"),
        etag="etag-123",
        ics_data=SAMPLE_VEVENT,
    )
    await store.save_resource(res)

    query = PropfindQuery(
        href="/work/event1.ics",
        depth=0,
        requested_props=[PropertyTag(DAV, "getetag")],
        user_id="user",
    )
    result = await engine.evaluate_propfind(store, p_store, query)
    assert len(result.responses) == 1
    ok_block = next(b for b in result.responses[0].propstats if b.status_code == 200)
    assert ok_block.properties[PropertyTag(DAV, "getetag")] == "etag-123"


@pytest.mark.asyncio
async def test_evaluate_propfind_missing_resource() -> None:
    """Test PROPFIND on a non-existent path raises FileNotFoundError."""
    engine = CoreWebDavEngine()
    store = MemoryStore()
    p_store = InMemoryPrincipalStore()

    query = PropfindQuery(
        href="/work/missing.ics",
        depth=0,
        requested_props=None,
        user_id="user",
    )
    with pytest.raises(FileNotFoundError):
        await engine.evaluate_propfind(store, p_store, query)


@pytest.mark.asyncio
async def test_evaluate_sync_collection() -> None:
    """Test sync-collection evaluation returns active resources and tombstones."""
    engine = CoreWebDavEngine()
    store = MemoryStore()
    await store.create_collection("/work")

    # Initial sync on empty collection
    init_res = await engine.evaluate_sync_collection(
        store, CollectionPath("/work"), SyncCollectionQuery(sync_token="")
    )
    assert len(init_res.responses) == 0
    token_0 = init_res.sync_token
    assert token_0 is not None

    # Add resource
    res = CalendarResource(
        path=ResourcePath.parse("/work/event1.ics"),
        etag="etag-123",
        ics_data=SAMPLE_VEVENT,
    )
    await store.save_resource(res)

    query = SyncCollectionQuery(sync_token=token_0, limit=5)
    result = await engine.evaluate_sync_collection(
        store, CollectionPath("/work"), query
    )
    assert len(result.responses) == 1
    assert result.responses[0].href == "/work/event1.ics"
    assert result.responses[0].etag == "etag-123"
    assert result.responses[0].ics_data == SAMPLE_VEVENT
    assert result.deleted_hrefs == []
    token_1 = result.sync_token
    assert token_1 is not None

    # Delete resource
    await store.delete_resource("/work/event1.ics")

    # Sync since token_1 returns deleted tombstone
    del_result = await engine.evaluate_sync_collection(
        store, CollectionPath("/work"), SyncCollectionQuery(sync_token=token_1)
    )
    assert len(del_result.responses) == 0
    assert del_result.deleted_hrefs == ["/work/event1.ics"]


@pytest.mark.asyncio
async def test_evaluate_calendar_query() -> None:
    """Test calendar-query filtering."""
    engine = CoreWebDavEngine()
    store = MemoryStore()
    await store.create_collection("/work")
    res = CalendarResource(
        path=ResourcePath.parse("/work/event1.ics"),
        etag="etag-123",
        ics_data=SAMPLE_VEVENT,
    )
    await store.save_resource(res)

    # 1. Matching filter
    filter_match = CompFilter(
        name="VCALENDAR",
        comp_filters=[CompFilter(name="VEVENT")],
    )
    query_match = CalendarQuery(
        comp_filter=filter_match,
        props=[PropertyTag(CALDAV, "calendar-data")],
    )
    result_match = await engine.evaluate_calendar_query(
        store, CollectionPath("/work"), query_match
    )
    assert len(result_match.responses) == 1
    assert result_match.responses[0].ics_data == SAMPLE_VEVENT

    # 2. Non-matching filter
    filter_miss = CompFilter(
        name="VCALENDAR",
        comp_filters=[CompFilter(name="VTODO")],
    )
    query_miss = CalendarQuery(
        comp_filter=filter_miss,
        props=[PropertyTag(CALDAV, "calendar-data")],
    )
    result_miss = await engine.evaluate_calendar_query(
        store, CollectionPath("/work"), query_miss
    )
    assert len(result_miss.responses) == 0


@pytest.mark.asyncio
async def test_evaluate_calendar_multiget() -> None:
    """Test calendar-multiget retrieval."""
    engine = CoreWebDavEngine()
    store = MemoryStore()
    await store.create_collection("/work")
    res = CalendarResource(
        path=ResourcePath.parse("/work/event1.ics"),
        etag="etag-123",
        ics_data=SAMPLE_VEVENT,
    )
    await store.save_resource(res)

    query = CalendarMultigetQuery(
        hrefs=["/work/event1.ics", "/work/missing.ics"],
        props=[PropertyTag(CALDAV, "calendar-data")],
    )
    result = await engine.evaluate_calendar_multiget(store, query)
    assert len(result.responses) == 1
    assert result.responses[0].href == "/work/event1.ics"
    assert result.responses[0].ics_data == SAMPLE_VEVENT
    assert result.missing_hrefs == ["/work/missing.ics"]


@pytest.mark.asyncio
async def test_evaluate_principal_search() -> None:
    """Test principal-property-search."""
    engine = CoreWebDavEngine()
    p_store = InMemoryPrincipalStore()

    # Create dummy principal
    dummy = PrincipalInfo(
        user_id="testuser",
        principal_path="/principals/testuser/",
        calendar_home_path="/calendars/testuser/",
        email="mailto:test@example.com",
    )
    p_store._principals["testuser"] = dummy

    # 1. Search with criteria matching term
    query_search = PrincipalSearchQuery(
        criteria=[SearchCriteria(prop_tag="email", match="test@example.com")],
        props=[PropertyTag(DAV, "displayname")],
        user_id="testuser",
    )
    result_search = await engine.evaluate_principal_search(p_store, query_search)
    assert len(result_search.responses) == 1
    assert result_search.responses[0].href == "/principals/testuser/"

    # 2. Search without criteria (resolves default user)
    query_default = PrincipalSearchQuery(
        criteria=[],
        props=[PropertyTag(DAV, "displayname")],
        user_id="testuser",
    )
    result_default = await engine.evaluate_principal_search(p_store, query_default)
    assert len(result_default.responses) == 1
    assert result_default.responses[0].href == "/principals/testuser/"
