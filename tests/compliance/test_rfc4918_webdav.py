"""Normative compliance test suite for RFC 4918 (WebDAV Core Protocol)."""

import aiohttp
import pytest

from icaldav.store.types import PropertyTag
from icaldav.xml.namespaces import DAV
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


@pytest.mark.asyncio
async def test_rfc4918_copy_resource(harness: ComplianceHarness) -> None:
    """RFC 4918 §9.8: COPY method duplicates resource with Destination and Overwrite header handling."""
    await harness.test_client.request("MKCALENDAR", "/src-cal")
    await harness.test_client.request("MKCALENDAR", "/dst-cal")

    src_url = f"{harness.base_url}src-cal/event1.ics"
    dst_url = f"{harness.base_url}dst-cal/copied.ics"

    # PUT original resource
    await harness.client.put_resource(src_url, SAMPLE_RESOURCE)

    # 1. COPY to new destination returns 201 Created
    status = await harness.client.copy_resource(src_url, dst_url)
    assert status == 201

    # Both resources exist and have matching content
    src_ics, _src_etag = await harness.client.get_resource(src_url)
    dst_ics, _dst_etag = await harness.client.get_resource(dst_url)
    assert src_ics == SAMPLE_RESOURCE
    assert dst_ics == SAMPLE_RESOURCE

    # 2. COPY with Overwrite=F returns 412 Precondition Failed
    with pytest.raises(aiohttp.ClientResponseError):
        await harness.client.copy_resource(src_url, dst_url, overwrite=False)

    # 3. COPY with Overwrite=T returns 204 No Content
    status_ow = await harness.client.copy_resource(src_url, dst_url, overwrite=True)
    assert status_ow == 204


@pytest.mark.asyncio
async def test_rfc4918_move_resource(harness: ComplianceHarness) -> None:
    """RFC 4918 §9.9: MOVE method relocates resource to new destination."""
    await harness.test_client.request("MKCALENDAR", "/move-src")
    await harness.test_client.request("MKCALENDAR", "/move-dst")

    src_url = f"{harness.base_url}move-src/event.ics"
    dst_url = f"{harness.base_url}move-dst/moved.ics"

    await harness.client.put_resource(src_url, SAMPLE_RESOURCE)

    # MOVE relocates resource (returns 201 Created)
    status = await harness.client.move_resource(src_url, dst_url)
    assert status == 201

    # Source is deleted
    with pytest.raises(aiohttp.ClientResponseError):
        await harness.client.get_resource(src_url)

    # Destination contains the resource
    dst_ics, _dst_etag = await harness.client.get_resource(dst_url)
    assert dst_ics == SAMPLE_RESOURCE


@pytest.mark.asyncio
async def test_rfc4918_proppatch_custom_and_protected(
    harness: ComplianceHarness,
) -> None:
    """RFC 4918 §9.2: PROPPATCH updates custom properties and rejects protected properties with 403."""

    await harness.test_client.request("MKCALENDAR", "/patch-cal")

    cal_url = f"{harness.base_url}patch-cal"
    custom_tag = PropertyTag("http://example.com/ns", "color")
    name_tag = PropertyTag(DAV, "displayname")

    # 1. Update custom property and displayname
    res = await harness.client.proppatch(
        cal_url,
        set_props={name_tag: "Updated Calendar Title", custom_tag: "green"},
    )
    assert res[name_tag] == 200
    assert res[custom_tag] == 200

    # 2. PROPFIND verifies displayname was updated (RFC 4918 §14.11)
    items = await harness.client.propfind(f"{cal_url}/", depth=0)
    assert len(items) == 1
    assert items[0].displayname == "Updated Calendar Title"

    # 3. Attempting to modify protected property (DAV:resourcetype) fails atomically
    prot_tag = PropertyTag(DAV, "resourcetype")
    res_fail = await harness.client.proppatch(
        cal_url,
        set_props={prot_tag: "collection", custom_tag: "red"},
    )
    assert res_fail[prot_tag] == 403
    assert res_fail[custom_tag] == 424
