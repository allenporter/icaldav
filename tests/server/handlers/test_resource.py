"""Unit tests for server GET/PUT/DELETE resource handlers."""

import pytest
from aiohttp.test_utils import TestClient, TestServer

from icaldav.server.router import create_app
from icaldav.store.memory import MemoryStore


@pytest.mark.asyncio
async def test_resource_get_put_delete_flow() -> None:
    """Test full HTTP GET, PUT, and DELETE flow on calendar resources."""
    store = MemoryStore()
    app = create_app(store)
    async with TestClient(TestServer(app)) as client:
        # GET non-existent returns 404
        assert (await client.get("/work/event1.ics")).status == 404

        # DELETE non-existent returns 404
        assert (await client.delete("/work/event1.ics")).status == 404

        # PUT resource
        ics_payload = (
            "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:123\r\nEND:VEVENT\r\nEND:VCALENDAR"
        )
        put_resp = await client.put("/work/event1.ics", data=ics_payload)
        assert put_resp.status == 201

        # PUT update existing resource returns 204
        put_update = await client.put("/work/event1.ics", data=ics_payload)
        assert put_update.status == 204

        # GET returns 200 OK
        get_resp = await client.get("/work/event1.ics")
        assert get_resp.status == 200
        assert await get_resp.text() == ics_payload

        # DELETE returns 204
        del_resp = await client.delete("/work/event1.ics")
        assert del_resp.status == 204


@pytest.mark.asyncio
async def test_resource_preconditions() -> None:
    """Test If-Match and If-None-Match HTTP conditional requests."""
    store = MemoryStore()
    app = create_app(store)
    ics_payload = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:123\r\nEND:VEVENT\r\nEND:VCALENDAR"
    )

    async with TestClient(TestServer(app)) as client:
        # If-Match: * on non-existent resource fails with 412
        resp = await client.put(
            "/work/event1.ics", data=ics_payload, headers={"If-Match": "*"}
        )
        assert resp.status == 412

        # If-None-Match: * on non-existent resource succeeds (201 Created)
        resp = await client.put(
            "/work/event1.ics", data=ics_payload, headers={"If-None-Match": "*"}
        )
        assert resp.status == 201
        etag = resp.headers.get("ETag")
        assert etag is not None

        # If-None-Match: * on existing resource fails with 412
        resp = await client.put(
            "/work/event1.ics", data=ics_payload, headers={"If-None-Match": "*"}
        )
        assert resp.status == 412

        # If-Match with matching ETag succeeds (204 No Content)
        resp = await client.put(
            "/work/event1.ics", data=ics_payload, headers={"If-Match": etag}
        )
        assert resp.status == 204

        # If-Match with wrong ETag fails with 412
        resp = await client.put(
            "/work/event1.ics",
            data=ics_payload,
            headers={"If-Match": '"wrong-etag"'},
        )
        assert resp.status == 412

        # DELETE with wrong ETag fails with 412
        resp = await client.delete(
            "/work/event1.ics", headers={"If-Match": '"wrong-etag"'}
        )
        assert resp.status == 412

        # DELETE with matching ETag succeeds with 204
        resp = await client.delete("/work/event1.ics", headers={"If-Match": etag})
        assert resp.status == 204


@pytest.mark.asyncio
async def test_resource_copy_and_move() -> None:
    """Test COPY and MOVE HTTP handlers on resources."""
    store = MemoryStore()
    app = create_app(store)
    ics_payload = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:123\r\nEND:VEVENT\r\nEND:VCALENDAR"
    )

    async with (
        TestServer(app) as server,
        TestClient(server) as client,
    ):
        await store.create_collection("/work")
        await store.create_collection("/archive")

        # PUT initial resource in /work
        assert (await client.put("/work/event.ics", data=ics_payload)).status == 201

        # COPY without Destination header fails with 400
        resp_no_dest = await client.request("COPY", "/work/event.ics")
        assert resp_no_dest.status == 400

        # COPY with invalid Overwrite header fails with 400
        resp_bad_ow = await client.request(
            "COPY",
            "/work/event.ics",
            headers={"Destination": "/archive/event.ics", "Overwrite": "INVALID"},
        )
        assert resp_bad_ow.status == 400

        # COPY to external host fails with 502
        resp_502 = await client.request(
            "COPY",
            "/work/event.ics",
            headers={"Destination": "http://other-host.example.com/archive/event.ics"},
        )
        assert resp_502.status == 502

        # COPY to same URI fails with 403
        resp_same = await client.request(
            "COPY",
            "/work/event.ics",
            headers={"Destination": "/work/event.ics"},
        )
        assert resp_same.status == 403

        # COPY to non-existent collection fails with 409
        resp_no_coll = await client.request(
            "COPY",
            "/work/event.ics",
            headers={"Destination": "/nonexistent/event.ics"},
        )
        assert resp_no_coll.status == 409

        # COPY creates new resource in /archive (201 Created)
        resp_copy = await client.request(
            "COPY",
            "/work/event.ics",
            headers={"Destination": "/archive/event.ics"},
        )
        assert resp_copy.status == 201

        # Verify resource exists in both places
        assert (await client.get("/work/event.ics")).status == 200
        assert (await client.get("/archive/event.ics")).status == 200

        # COPY to existing with Overwrite: F fails with 412
        resp_ow_f = await client.request(
            "COPY",
            "/work/event.ics",
            headers={"Destination": "/archive/event.ics", "Overwrite": "F"},
        )
        assert resp_ow_f.status == 412

        # COPY to existing with Overwrite: T overwrites (204 No Content)
        resp_ow_t = await client.request(
            "COPY",
            "/work/event.ics",
            headers={"Destination": "/archive/event.ics", "Overwrite": "T"},
        )
        assert resp_ow_t.status == 204

        # MOVE resource from /work to /archive/moved.ics (201 Created)
        resp_move = await client.request(
            "MOVE",
            "/work/event.ics",
            headers={"Destination": "/archive/moved.ics"},
        )
        assert resp_move.status == 201

        # Source is gone, destination exists
        assert (await client.get("/work/event.ics")).status == 404
        assert (await client.get("/archive/moved.ics")).status == 200


@pytest.mark.asyncio
async def test_resource_proppatch() -> None:
    """Test PROPPATCH HTTP handler on resources."""
    store = MemoryStore()
    app = create_app(store)
    ics_payload = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:123\r\nEND:VEVENT\r\nEND:VCALENDAR"
    )

    async with (
        TestServer(app) as server,
        TestClient(server) as client,
    ):
        await store.create_collection("/work")
        await client.put("/work/event.ics", data=ics_payload)

        # 1. PROPPATCH on non-existent returns 404
        proppatch_body = (
            '<?xml version="1.0"?>'
            '<D:propertyupdate xmlns:D="DAV:" xmlns:Z="http://example.com/ns">'
            "<D:set><D:prop><Z:tag>urgent</Z:tag></D:prop></D:set>"
            "</D:propertyupdate>"
        )
        resp_404 = await client.request(
            "PROPPATCH", "/work/missing.ics", data=proppatch_body
        )
        assert resp_404.status == 404

        # 2. PROPPATCH custom dead property succeeds with 207 Multi-Status
        resp_207 = await client.request(
            "PROPPATCH", "/work/event.ics", data=proppatch_body
        )
        assert resp_207.status == 207
        assert "200 OK" in await resp_207.text()

        # 3. PROPPATCH protected property (DAV:getetag) fails with 403 & 424
        protected_patch = (
            '<?xml version="1.0"?>'
            '<D:propertyupdate xmlns:D="DAV:" xmlns:Z="http://example.com/ns">'
            "<D:set><D:prop><D:getetag>fake-etag</D:getetag><Z:other>val</Z:other></D:prop></D:set>"
            "</D:propertyupdate>"
        )
        resp_prot = await client.request(
            "PROPPATCH", "/work/event.ics", data=protected_patch
        )
        assert resp_prot.status == 207
        resp_text = await resp_prot.text()
        assert "403 Forbidden" in resp_text
        assert "424 Failed Dependency" in resp_text
