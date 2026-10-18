"""Unit tests for server REPORT handlers."""

import pytest
from aiohttp.test_utils import TestClient, TestServer

from icaldav.client.client import CalDavClient
from icaldav.server.router import create_app
from icaldav.store.memory import MemoryStore
from icaldav.store.principal import InMemoryPrincipalStore, PrincipalInfo
from icaldav.xml.report.request import build_calendar_multiget_xml


@pytest.mark.asyncio
async def test_report_error_paths() -> None:
    """Test router error responses for invalid REPORT requests."""
    store = MemoryStore()
    app = create_app(store)
    async with TestClient(TestServer(app)) as client:
        # Empty body REPORT returns 400
        resp = await client.request("REPORT", "/work", data="")
        assert resp.status == 400

        # Invalid XML REPORT returns 400
        resp = await client.request("REPORT", "/work", data="<not-valid-xml")
        assert resp.status == 400

        # Unsupported REPORT type tag returns 400
        resp = await client.request(
            "REPORT", "/work", data="<unsupported-report xmlns='DAV:'/>"
        )
        assert resp.status == 400


@pytest.mark.asyncio
async def test_report_calendar_multiget_collection_scoping() -> None:
    """Test calendar-multiget scopes hrefs to the target collection."""
    store = MemoryStore()
    app = create_app(store)
    ics_work = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:work-1\r\nEND:VEVENT\r\nEND:VCALENDAR"
    )
    ics_personal = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:secret-1\r\nEND:VEVENT\r\nEND:VCALENDAR"
    )

    async with TestClient(TestServer(app)) as client:
        assert (await client.put("/work/ev1.ics", data=ics_work)).status == 201
        assert (
            await client.put("/personal/secret.ics", data=ics_personal)
        ).status == 201

        multiget_xml = build_calendar_multiget_xml(
            hrefs=["/work/ev1.ics", "/personal/secret.ics", "/"]
        )
        resp = await client.request("REPORT", "/work/", data=multiget_xml)
        assert resp.status == 207
        xml_text = await resp.text()
        assert "UID:work-1" in xml_text
        assert "UID:secret-1" not in xml_text
        assert "HTTP/1.1 200 OK" in xml_text
        assert "HTTP/1.1 404 Not Found" in xml_text
        assert "/personal/secret.ics" in xml_text


@pytest.mark.asyncio
async def test_report_principal_property_search() -> None:
    """Test principal-property-search REPORT filtering using CalDavClient."""
    p_alice = PrincipalInfo(
        user_id="alice",
        principal_path="/principals/alice/",
        calendar_home_path="/calendars/alice/",
        email="mailto:alice@example.com",
    )
    p_bob = PrincipalInfo(
        user_id="bob",
        principal_path="/principals/bob/",
        calendar_home_path="/calendars/bob/",
        email="mailto:bob@example.com",
    )
    p_store = InMemoryPrincipalStore(principals=[p_alice, p_bob])
    store = MemoryStore()
    app = create_app(store, principal_store=p_store)

    async with (
        TestClient(TestServer(app)) as test_client,
        CalDavClient(session=test_client.session) as caldav_client,
    ):
        # Search matching 'alice'
        results_alice = await caldav_client.principal_property_search(
            url=str(test_client.make_url("/")),
            match="alice",
        )
        assert len(results_alice) == 1
        assert results_alice[0].href == "/principals/alice/"

        # Search matching non-existent user
        results_none = await caldav_client.principal_property_search(
            url=str(test_client.make_url("/")),
            match="nonexistent",
        )
        assert len(results_none) == 0


@pytest.mark.asyncio
async def test_report_sync_collection() -> None:
    """Test sync-collection REPORT dispatching using CalDavClient."""
    store = MemoryStore()
    app = create_app(store)
    async with (
        TestClient(TestServer(app)) as test_client,
        CalDavClient(session=test_client.session) as caldav_client,
    ):
        resources, _ = await caldav_client.sync_collection(
            url=str(test_client.make_url("/work/")),
            sync_token="http://icaldav.org/ns/sync-tokens/1",
        )
        assert isinstance(resources, list)
