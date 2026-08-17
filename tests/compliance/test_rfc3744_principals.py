"""Normative compliance test suite for RFC 3744 (WebDAV ACL / Principals), RFC 5397, and RFC 6764."""

import pytest

from tests.compliance.conftest import ComplianceHarness


@pytest.mark.asyncio
async def test_rfc3744_principal_property_search(harness: ComplianceHarness) -> None:
    """RFC 3744 §9.4: principal-property-search REPORT searches principal directory."""
    # PrincipalStore is populated with Alice and Bob by default
    results = await harness.client.principal_property_search(
        url=f"{harness.base_url}principals/",
        match="Alice",
    )
    assert len(results) == 1
    assert "alice" in results[0].href.lower()


@pytest.mark.asyncio
async def test_rfc5397_current_user_principal(harness: ComplianceHarness) -> None:
    """RFC 5397: PROPFIND on root or collection returns current-user-principal property."""
    items = await harness.client.propfind(
        f"{harness.base_url}",
        depth=0,
        props=["current-user-principal", "resourcetype"],
    )
    assert len(items) == 1


@pytest.mark.asyncio
async def test_rfc6764_well_known_caldav(harness: ComplianceHarness) -> None:
    """RFC 6764: GET /.well-known/caldav redirects to CalDAV service root."""
    resp = await harness.test_client.get("/.well-known/caldav", allow_redirects=False)
    assert resp.status in (301, 307, 308)
    assert resp.headers.get("Location") == "/"
