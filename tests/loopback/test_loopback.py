"""Zero-I/O in-process loopback integration test connecting CalDavClient to CalDavRouter.

RFC References:
  - RFC 4918 Section 9.1: PROPFIND Method.
  - RFC 4918 Section 9.7: DELETE Method.
  - RFC 4791 Section 5.2: Calendar Object Resources (GET / PUT).
"""

import pytest
from aiohttp.test_utils import TestClient, TestServer

from icaldav.client.client import CalDavClient
from icaldav.server.router import create_app
from icaldav.store.memory import MemoryStore


@pytest.mark.asyncio
async def test_in_process_loopback_sync_flow() -> None:
    """Test full client-server interaction in-process with zero network I/O."""
    store = MemoryStore()
    app = create_app(store)

    server = TestServer(app)
    async with TestClient(server) as test_http_client:
        # Pass test_http_client.session to CalDavClient for zero-I/O loopback
        async with CalDavClient(session=test_http_client.session) as client:
            base_url = str(server.make_url("/work"))

            # 1. PROPFIND on empty collection
            items = await client.propfind(base_url, depth=1)
            assert len(items) == 1
            assert items[0].is_collection is True

            # 2. PUT a calendar resource
            event_url = f"{base_url}/event1.ics"
            ics_data = (
                "BEGIN:VCALENDAR\r\n"
                "VERSION:2.0\r\n"
                "BEGIN:VEVENT\r\n"
                "UID:meeting-42\r\n"
                "SUMMARY:Team Sync\r\n"
                "END:VEVENT\r\n"
                "END:VCALENDAR"
            )
            etag = await client.put_resource(event_url, ics_data)
            assert etag != ""

            # 3. GET the uploaded calendar resource
            fetched_ics, fetched_etag = await client.get_resource(event_url)
            assert fetched_ics == ics_data
            assert fetched_etag == etag

            # 4. PROPFIND listing now includes event1.ics
            items = await client.propfind(base_url, depth=1)
            assert len(items) == 2
            hrefs = [item.href for item in items]
            assert "/work/event1.ics" in hrefs

            # 5. DELETE the resource
            await client.delete_resource(event_url)

            # 6. Verify resource is removed
            items = await client.propfind(base_url, depth=1)
            assert len(items) == 1
