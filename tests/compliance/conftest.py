"""Pytest configuration and fixtures for RFC compliance test suites."""

from collections.abc import AsyncGenerator
from dataclasses import dataclass

import pytest
from aiohttp.test_utils import TestClient, TestServer

from icaldav.client.client import CalDavClient
from icaldav.server.router import create_app
from icaldav.store.memory import MemoryStore
from icaldav.store.principal import (
    InMemoryPrincipalStore,
    PrincipalInfo,
    PrincipalStore,
)
from icaldav.store.sqlite import SQLiteStore
from icaldav.store.types import LocalStore


@dataclass
class ComplianceHarness:
    """End-to-end test harness for executing RFC compliance test cases."""

    client: CalDavClient
    test_client: TestClient
    server: TestServer
    store: LocalStore
    principal_store: PrincipalStore
    base_url: str


@pytest.fixture(params=["memory", "sqlite"])
async def harness(request: pytest.FixtureRequest) -> AsyncGenerator[ComplianceHarness]:
    """Provide a running CalDavRouter application backed by each storage engine."""
    principal_store = InMemoryPrincipalStore(
        principals=[
            PrincipalInfo(
                user_id="alice",
                principal_path="/principals/alice/",
                calendar_home_path="/",
                email="mailto:alice@example.com",
            ),
            PrincipalInfo(
                user_id="bob",
                principal_path="/principals/bob/",
                calendar_home_path="/",
                email="mailto:bob@example.com",
            ),
        ]
    )
    if request.param == "memory":
        store: LocalStore = MemoryStore()
    elif request.param == "sqlite":
        store = SQLiteStore(":memory:")
    else:
        raise ValueError(f"Unknown backend: {request.param}")

    app = create_app(store=store, principal_store=principal_store)
    server = TestServer(app)
    async with (
        TestClient(server) as test_http_client,
        CalDavClient(session=test_http_client.session) as client,
    ):
        base_url = str(server.make_url("/"))
        yield ComplianceHarness(
            client=client,
            test_client=test_http_client,
            server=server,
            store=store,
            principal_store=principal_store,
            base_url=base_url,
        )

    if isinstance(store, SQLiteStore):
        await store.close()
