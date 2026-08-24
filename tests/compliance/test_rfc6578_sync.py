"""Normative compliance test suite for RFC 6578 (WebDAV Collection Synchronization)."""

import pytest

from tests.compliance.conftest import ComplianceHarness

SAMPLE_EVENT = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//Example Corp.//EN\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:sync-event-1\r\n"
    "SUMMARY:Sync Test Event\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR"
)


@pytest.mark.asyncio
async def test_rfc6578_sync_collection_lifecycle(harness: ComplianceHarness) -> None:
    """RFC 6578 §3.1 & §3.2: Full sync-collection lifecycle with initial sync, delta updates, and tombstones."""
    await harness.test_client.request("MKCALENDAR", "/sync-test")
    cal_url = f"{harness.base_url}sync-test"

    # 1. Initial sync on empty collection
    res0, token0 = await harness.client.sync_collection(cal_url, sync_token="")
    assert len(res0) == 0
    assert token0 is not None

    # 2. Add resource
    await harness.client.put_resource(f"{cal_url}/event1.ics", SAMPLE_EVENT)

    # 3. Delta sync since token0 returns event1
    res1, token1 = await harness.client.sync_collection(cal_url, sync_token=token0)
    assert len(res1) == 1
    assert res1[0].href == "/sync-test/event1.ics"
    assert token1 is not None

    # 4. Sync with token1 returns 0 updates (converged)
    res_converged, _ = await harness.client.sync_collection(cal_url, sync_token=token1)
    assert len(res_converged) == 0

    # 5. Delete event1
    del_resp = await harness.test_client.delete("/sync-test/event1.ics")
    assert del_resp.status == 204

    # 6. Raw REPORT request verifies 404 tombstone XML response
    report_body = f"""<?xml version="1.0" encoding="utf-8" ?>
<D:sync-collection xmlns:D="DAV:">
  <D:sync-token>{token1}</D:sync-token>
  <D:sync-level>1</D:sync-level>
  <D:prop><D:getetag/></D:prop>
</D:sync-collection>"""
    resp = await harness.test_client.request(
        "REPORT",
        "/sync-test",
        data=report_body,
        headers={"Content-Type": "application/xml"},
    )
    assert resp.status == 207
    xml_text = await resp.text()
    assert "HTTP/1.1 404 Not Found" in xml_text
    assert "/sync-test/event1.ics" in xml_text
    assert "sync-token>" in xml_text


@pytest.mark.asyncio
async def test_rfc6578_sync_token_property(harness: ComplianceHarness) -> None:
    """RFC 6578 §6.1: Collection PROPFIND advertises DAV:sync-token property."""
    await harness.test_client.request("MKCALENDAR", "/token-prop-test")
    cal_url = f"{harness.base_url}token-prop-test"

    items = await harness.client.propfind(f"{cal_url}/", depth=0, props=["sync-token"])
    assert len(items) == 1


@pytest.mark.asyncio
async def test_rfc6578_multipage_sync_pagination(harness: ComplianceHarness) -> None:
    """RFC 6578 §3.7: Multi-page sync token iteration and client auto-pagination."""
    await harness.test_client.request("MKCALENDAR", "/multipage-sync")
    cal_url = f"{harness.base_url}multipage-sync"

    # 1. Put 5 resources
    for i in range(1, 6):
        body = (
            f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
            f"UID:multi-{i}\r\nSUMMARY:Event {i}\r\nEND:VEVENT\r\nEND:VCALENDAR"
        )
        await harness.client.put_resource(f"{cal_url}/event{i}.ics", body)

    # 2. Step-by-step multi-page pagination using intermediate sync tokens
    res_p1, token_p1 = await harness.client.sync_collection(
        cal_url, sync_token="", limit=2, auto_paginate=False
    )
    assert len(res_p1) == 2
    assert token_p1 is not None

    res_p2, token_p2 = await harness.client.sync_collection(
        cal_url, sync_token=token_p1, limit=2, auto_paginate=False
    )
    assert len(res_p2) == 2
    assert token_p2 is not None
    assert token_p2 != token_p1

    res_p3, token_p3 = await harness.client.sync_collection(
        cal_url, sync_token=token_p2, limit=2, auto_paginate=False
    )
    assert len(res_p3) == 1
    assert token_p3 is not None

    all_manual_hrefs = [r.href for r in res_p1 + res_p2 + res_p3]
    assert len(all_manual_hrefs) == 5

    # 3. Verify client auto_paginate=True collects all 5 items in one call
    res_auto, token_auto = await harness.client.sync_collection(
        cal_url, sync_token="", limit=2, auto_paginate=True
    )
    assert len(res_auto) == 5
    assert token_auto == token_p3

    # 4. Modify event1, delete event2, and add event6
    await harness.client.put_resource(
        f"{cal_url}/event1.ics",
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:multi-1\r\nSUMMARY:Updated 1\r\nEND:VEVENT\r\nEND:VCALENDAR",
    )
    await harness.client.delete_resource(f"{cal_url}/event2.ics")
    await harness.client.put_resource(
        f"{cal_url}/event6.ics",
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:multi-6\r\nSUMMARY:Event 6\r\nEND:VEVENT\r\nEND:VCALENDAR",
    )

    # 5. Delta sync with auto_paginate=True and limit=1
    res_delta, token_delta = await harness.client.sync_collection(
        cal_url, sync_token=token_auto, limit=1, auto_paginate=True
    )
    delta_hrefs = [r.href for r in res_delta]
    assert "/multipage-sync/event1.ics" in delta_hrefs
    assert "/multipage-sync/event6.ics" in delta_hrefs
    assert token_delta is not None
    assert token_delta != token_auto
