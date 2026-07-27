"""Unit tests for server REPORT handlers."""

import pytest
from aiohttp.test_utils import TestClient, TestServer

from icaldav.client.client import CalDavClient
from icaldav.server.router import create_app
from icaldav.store.memory import MemoryStore
from icaldav.store.principal import InMemoryPrincipalStore, PrincipalInfo


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

    async with TestClient(TestServer(app)) as test_client:
        async with CalDavClient(session=test_client.session) as caldav_client:
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
    """Test sync-collection REPORT dispatching in router."""
    store = MemoryStore()
    app = create_app(store)
    async with TestClient(TestServer(app)) as client:
        sync_xml = (
            b"<?xml version='1.0' encoding='utf-8'?>"
            b"<d:sync-collection xmlns:d='DAV:'>"
            b"<d:sync-token>http://icaldav.org/ns/sync-tokens/1</d:sync-token>"
            b"</d:sync-collection>"
        )
        resp = await client.request("REPORT", "/work/", data=sync_xml)
        assert resp.status == 207
