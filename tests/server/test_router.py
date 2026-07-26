"""Unit tests for CalDavRouter application creation and top-level router dispatch."""

import pytest
from aiohttp.test_utils import TestClient, TestServer

from icaldav.server.router import CalDavRouter
from icaldav.store.memory import MemoryStore


@pytest.mark.asyncio
async def test_router_create_app() -> None:
    """Test CalDavRouter instantiation and create_app factory."""
    store = MemoryStore()
    router = CalDavRouter(store)
    app = router.create_app()
    assert app is not None

    async with TestClient(TestServer(app)) as client:
        resp = await client.options("/work")
        assert resp.status == 200
        assert "PROPFIND" in resp.headers["Allow"]
        assert "calendar-access" in resp.headers["DAV"]

        resp_slash = await client.options("/work/")
        assert resp_slash.status == 200

        propfind_resp = await client.request("PROPFIND", "/work/")
        assert propfind_resp.status == 207

        report_resp = await client.request("REPORT", "/work/", data=b"invalid body")
        assert report_resp.status == 400


@pytest.mark.asyncio
async def test_router_with_custom_principal_store() -> None:
    """Test CalDavRouter with custom PrincipalStore integration."""
    from icaldav.store.principal import InMemoryPrincipalStore

    store = MemoryStore()
    p_store = InMemoryPrincipalStore.create_single_user(
        user_id="custom",
        principal_path="/principals/custom/",
        calendar_home_path="/custom_home/",
        email="mailto:custom@example.com",
    )
    router = CalDavRouter(store, principal_store=p_store)
    app = router.create_app()

    async with TestClient(TestServer(app)) as client:
        resp = await client.request("PROPFIND", "/")
        assert resp.status == 207
        body = await resp.text()
        assert "/principals/custom/" in body
        assert "/custom_home/" in body
