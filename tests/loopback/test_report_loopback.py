"""Loopback integration tests for CalDAV REPORT and MKCALENDAR methods.

Tests the full client-server round-trip for calendar-query, calendar-multiget,
and MKCALENDAR using in-process aiohttp TestServer with zero network I/O.

RFC References:
  - RFC 4791 Section 7.8: calendar-query REPORT.
  - RFC 4791 Section 7.9: calendar-multiget REPORT.
  - RFC 4791 Section 5.3.1: MKCALENDAR Method.
"""

import pytest
from aiohttp.test_utils import TestClient, TestServer

from icaldav.client.client import CalDavClient
from icaldav.server.router import create_app
from icaldav.store.memory import MemoryStore

VEVENT_JULY = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:july-meeting@test\r\n"
    "DTSTART:20260715T100000Z\r\n"
    "DTEND:20260715T110000Z\r\n"
    "SUMMARY:July Meeting\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR"
)

VEVENT_AUGUST = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:august-meeting@test\r\n"
    "DTSTART:20260805T140000Z\r\n"
    "DTEND:20260805T150000Z\r\n"
    "SUMMARY:August Meeting\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR"
)

VTODO_ICS = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "BEGIN:VTODO\r\n"
    "UID:task-1@test\r\n"
    "DTSTART:20260715T100000Z\r\n"
    "DUE:20260716T100000Z\r\n"
    "SUMMARY:Buy groceries\r\n"
    "END:VTODO\r\n"
    "END:VCALENDAR"
)


@pytest.fixture
async def client_and_base():
    """Create a test client connected to a CalDavRouter with sample data."""
    store = MemoryStore()
    app = create_app(store)
    server = TestServer(app)
    async with (
        TestClient(server) as test_http_client,
        CalDavClient(session=test_http_client.session) as client,
    ):
        base_url = str(server.make_url("/work"))
        # Pre-populate with test data
        await client.put_resource(f"{base_url}/july.ics", VEVENT_JULY)
        await client.put_resource(f"{base_url}/august.ics", VEVENT_AUGUST)
        await client.put_resource(f"{base_url}/todo.ics", VTODO_ICS)
        yield client, base_url, server


@pytest.mark.asyncio
async def test_calendar_query_all_vevents(client_and_base) -> None:
    """calendar-query REPORT filtering for all VEVENTs returns both events."""
    client, base_url, _ = client_and_base
    resources = await client.calendar_query(base_url, component="VEVENT")
    assert len(resources) == 2
    hrefs = {r.href for r in resources}
    assert "/work/july.ics" in hrefs
    assert "/work/august.ics" in hrefs
    # Verify ics_data is returned
    for r in resources:
        assert r.ics_data is not None
        assert "BEGIN:VCALENDAR" in r.ics_data


@pytest.mark.asyncio
async def test_calendar_query_time_range(client_and_base) -> None:
    """calendar-query REPORT with time-range returns only July event."""
    client, base_url, _ = client_and_base
    resources = await client.calendar_query(
        base_url,
        component="VEVENT",
        time_start="20260701T000000Z",
        time_end="20260801T000000Z",
    )
    assert len(resources) == 1
    assert resources[0].href == "/work/july.ics"
    assert "July Meeting" in (resources[0].ics_data or "")


@pytest.mark.asyncio
async def test_calendar_query_vtodo(client_and_base) -> None:
    """calendar-query REPORT filtering for VTODO returns only todo."""
    client, base_url, _ = client_and_base
    resources = await client.calendar_query(base_url, component="VTODO")
    assert len(resources) == 1
    assert resources[0].href == "/work/todo.ics"


@pytest.mark.asyncio
async def test_calendar_query_empty_result(client_and_base) -> None:
    """calendar-query REPORT for non-existent component returns empty list."""
    client, base_url, _ = client_and_base
    resources = await client.calendar_query(base_url, component="VJOURNAL")
    assert len(resources) == 0


@pytest.mark.asyncio
async def test_calendar_multiget(client_and_base) -> None:
    """calendar-multiget REPORT with multiple hrefs returns specified resources."""
    client, base_url, _ = client_and_base
    resources = await client.calendar_multiget(
        base_url,
        hrefs=["/work/july.ics", "/work/august.ics"],
    )
    assert len(resources) == 2
    hrefs = {r.href for r in resources}
    assert "/work/july.ics" in hrefs
    assert "/work/august.ics" in hrefs


@pytest.mark.asyncio
async def test_calendar_multiget_missing_href(client_and_base) -> None:
    """calendar-multiget REPORT with a missing href only returns found resources."""
    client, base_url, _ = client_and_base
    resources = await client.calendar_multiget(
        base_url,
        hrefs=["/work/july.ics", "/work/nonexistent.ics"],
    )
    # Only the found resource should be returned (missing hrefs get 404 propstat)
    assert len(resources) == 1
    assert resources[0].href == "/work/july.ics"


@pytest.mark.asyncio
async def test_mkcalendar() -> None:
    """MKCALENDAR creates a new collection that can be queried with PROPFIND."""
    store = MemoryStore()
    app = create_app(store)
    server = TestServer(app)
    async with TestClient(server) as test_http_client:
        # MKCALENDAR
        resp = await test_http_client.request("MKCALENDAR", "/newcal")
        assert resp.status == 201

        # Verify collection exists via PROPFIND
        async with CalDavClient(session=test_http_client.session) as client:
            items = await client.propfind(str(server.make_url("/newcal")), depth=1)
            assert len(items) == 1
            assert items[0].is_collection is True


@pytest.mark.asyncio
async def test_mkcalendar_duplicate() -> None:
    """MKCALENDAR on existing collection returns 405."""
    store = MemoryStore()
    app = create_app(store)
    server = TestServer(app)
    async with TestClient(server) as test_http_client:
        # Create once
        resp = await test_http_client.request("MKCALENDAR", "/work")
        assert resp.status == 201

        # Duplicate should fail
        resp = await test_http_client.request("MKCALENDAR", "/work")
        assert resp.status == 405


@pytest.mark.asyncio
async def test_well_known_caldav_redirect() -> None:
    """/.well-known/caldav returns 301 redirect to /."""
    store = MemoryStore()
    app = create_app(store)
    server = TestServer(app)
    async with TestClient(server) as test_http_client:
        resp = await test_http_client.get("/.well-known/caldav", allow_redirects=False)
        assert resp.status == 301
        assert resp.headers["Location"] == "/"


@pytest.mark.asyncio
async def test_sync_collection_delta_tombstones() -> None:
    """Test sync-collection loopback returns initial resources and deleted tombstones."""
    store = MemoryStore()
    app = create_app(store)
    server = TestServer(app)
    async with (
        TestClient(server) as test_http_client,
        CalDavClient(session=test_http_client.session) as client,
    ):
        base_url = str(server.make_url("/work"))
        await client.put_resource(f"{base_url}/event1.ics", VEVENT_JULY)

        # Initial sync returns event1
        res1, token1 = await client.sync_collection(base_url, sync_token="")
        assert len(res1) == 1
        assert res1[0].href == "/work/event1.ics"
        assert token1 is not None

        # Delete event1
        del_resp = await test_http_client.delete("/work/event1.ics")
        assert del_resp.status == 204

        # REPORT request body with token1
        body = f"""<?xml version="1.0" encoding="utf-8" ?>
<D:sync-collection xmlns:D="DAV:">
  <D:sync-token>{token1}</D:sync-token>
  <D:sync-level>1</D:sync-level>
  <D:prop><D:getetag/></D:prop>
</D:sync-collection>"""
        headers = {"Content-Type": "application/xml; charset=utf-8"}
        resp = await test_http_client.request(
            "REPORT", "/work", data=body, headers=headers
        )
        assert resp.status == 207
        xml_text = await resp.text()
        assert "HTTP/1.1 404 Not Found" in xml_text
        assert "sync-token>" in xml_text
