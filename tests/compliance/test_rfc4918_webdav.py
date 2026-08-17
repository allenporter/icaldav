"""Normative compliance test suite for RFC 4918 (WebDAV Core Protocol)."""

import pytest

from tests.compliance.conftest import ComplianceHarness

SAMPLE_RESOURCE = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//Example Corp.//EN\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:webdav-test-event\r\n"
    "SUMMARY:WebDAV Spec Event\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR"
)


@pytest.mark.asyncio
async def test_rfc4918_propfind_depth_0_and_1(harness: ComplianceHarness) -> None:
    """RFC 4918 §9.1: PROPFIND with Depth 0 and Depth 1 semantics."""
    await harness.test_client.request("MKCALENDAR", "/props")
    cal_url = f"{harness.base_url}props"

    await harness.client.put_resource(f"{cal_url}/event1.ics", SAMPLE_RESOURCE)

    # 1. Depth 0 returns only the target collection
    items_d0 = await harness.client.propfind(f"{cal_url}/", depth=0)
    assert len(items_d0) == 1
    assert items_d0[0].is_collection is True

    # 2. Depth 1 returns target collection and child resources
    items_d1 = await harness.client.propfind(f"{cal_url}/", depth=1)
    assert len(items_d1) == 2
    hrefs = {item.href for item in items_d1}
    assert "/props/" in hrefs or "/props" in hrefs
    assert "/props/event1.ics" in hrefs


@pytest.mark.asyncio
async def test_rfc4918_get_and_put_etags(harness: ComplianceHarness) -> None:
    """RFC 4918 §9.4 & §9.7: PUT creates resource with ETag; GET returns exact content and matching ETag."""
    await harness.test_client.request("MKCALENDAR", "/etag-test")

    # PUT creates resource and returns ETag
    put_resp = await harness.test_client.put(
        "/etag-test/event.ics", data=SAMPLE_RESOURCE
    )
    assert put_resp.status == 201
    etag = put_resp.headers.get("ETag")
    assert etag is not None

    # GET returns content and same ETag
    get_resp = await harness.test_client.get("/etag-test/event.ics")
    assert get_resp.status == 200
    assert get_resp.headers.get("ETag") == etag
    assert (await get_resp.text()) == SAMPLE_RESOURCE


@pytest.mark.asyncio
async def test_rfc4918_conditional_preconditions(harness: ComplianceHarness) -> None:
    """RFC 4918 / RFC 7232: Evaluate If-Match and If-None-Match preconditions."""
    await harness.test_client.request("MKCALENDAR", "/precond-test")

    # 1. If-Match: * fails when resource does not exist (412)
    resp = await harness.test_client.put(
        "/precond-test/res.ics",
        data=SAMPLE_RESOURCE,
        headers={"If-Match": "*"},
    )
    assert resp.status == 412

    # 2. If-None-Match: * succeeds when resource does not exist (201)
    resp = await harness.test_client.put(
        "/precond-test/res.ics",
        data=SAMPLE_RESOURCE,
        headers={"If-None-Match": "*"},
    )
    assert resp.status == 201
    etag = resp.headers.get("ETag")
    assert etag is not None

    # 3. If-None-Match: * fails when resource already exists (412)
    resp = await harness.test_client.put(
        "/precond-test/res.ics",
        data=SAMPLE_RESOURCE,
        headers={"If-None-Match": "*"},
    )
    assert resp.status == 412

    # 4. If-Match with wrong ETag fails (412)
    resp = await harness.test_client.put(
        "/precond-test/res.ics",
        data=SAMPLE_RESOURCE,
        headers={"If-Match": '"wrong-etag"'},
    )
    assert resp.status == 412

    # 5. If-Match with matching ETag succeeds (204 No Content)
    resp = await harness.test_client.put(
        "/precond-test/res.ics",
        data=SAMPLE_RESOURCE,
        headers={"If-Match": etag},
    )
    assert resp.status == 204

    # 6. DELETE with matching ETag succeeds (204)
    del_resp = await harness.test_client.delete(
        "/precond-test/res.ics",
        headers={"If-Match": etag},
    )
    assert del_resp.status == 204
