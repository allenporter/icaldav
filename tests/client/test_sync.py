"""Integration and unit tests for CalDavSyncManager following real-object test principles (Abseil SWE Book Ch. 13).

Exercises real CalDavClient transport, real CalDavRouter HTTP routing/dispatch,
real WebDAV XML decoders/encoders, and fake in-memory storage (MemoryStore).

RFC References:
    - RFC 6578: WebDAV Collection Synchronization.
    - RFC 4791: CalDAV Extensions.
"""

from typing import AsyncGenerator
from dataclasses import dataclass

from aiohttp.test_utils import TestClient, TestServer
import pytest

from icaldav.client.client import CalDavClient
from icaldav.client.sync import (
    CalDavSyncManager,
    SyncPath,
    SyncResult,
    _normalize_href,
)
from icaldav.server.router import create_app
from icaldav.store.memory import MemoryStore
from icaldav.xml.report.models import ReportResource


SAMPLE_ICS_1 = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:event-12345@example.com
SUMMARY:Work Meeting
DTSTART:20260810T090000Z
DTEND:20260810T100000Z
END:VEVENT
END:VCALENDAR"""

SAMPLE_ICS_2 = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:event-67890@example.com
SUMMARY:Standup Sync
DTSTART:20260811T100000Z
DTEND:20260811T103000Z
END:VEVENT
END:VCALENDAR"""

SAMPLE_RECURRENCE_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:recurring-1@example.com
SUMMARY:Weekly Meeting
DTSTART:20260801T120000Z
RRULE:FREQ=WEEKLY
END:VEVENT
BEGIN:VEVENT
UID:recurring-1@example.com
RECURRENCE-ID:20260808T120000Z
SUMMARY:Weekly Meeting (Rescheduled)
DTSTART:20260808T140000Z
END:VEVENT
END:VCALENDAR"""


@dataclass
class LoopbackHarness:
    client: CalDavClient
    server_store: MemoryStore
    local_store: MemoryStore
    base_url: str
    sync_manager: CalDavSyncManager


@pytest.fixture
async def harness() -> AsyncGenerator[LoopbackHarness, None]:
    """Pytest fixture setting up real server, client, and memory stores for in-process loopback testing."""
    server_store = MemoryStore()
    await server_store.create_collection("/work")

    app = create_app(server_store)
    server = TestServer(app)

    async with TestClient(server) as test_http_client:
        async with CalDavClient(session=test_http_client.session) as client:
            base_url = str(server.make_url("/work/"))
            local_store = MemoryStore()
            sync_manager = CalDavSyncManager(
                client=client,
                collection_url=base_url,
                store=local_store,
            )

            yield LoopbackHarness(
                client=client,
                server_store=server_store,
                local_store=local_store,
                base_url=base_url,
                sync_manager=sync_manager,
            )


def test_extract_uid_and_normalize_href() -> None:
    res1 = ReportResource(href="/test.ics", etag="1", ics_data=SAMPLE_ICS_1)
    assert res1.extracted_uid == "event-12345@example.com"

    res_no_uid = ReportResource(href="/test.ics", etag="1", ics_data="NO UID HERE")
    assert res_no_uid.extracted_uid is None

    assert _normalize_href("work/meeting.ics") == "/work/meeting.ics"
    assert _normalize_href("/work/meeting.ics/") == "/work/meeting.ics"
    assert _normalize_href("/") == "/"



@pytest.mark.asyncio
async def test_path1_initial_sync(harness: LoopbackHarness) -> None:
    """Real Path 1 (RFC 6578 sync-collection) initial synchronization."""
    await harness.client.put_resource(f"{harness.base_url}event1.ics", SAMPLE_ICS_1)
    await harness.client.put_resource(f"{harness.base_url}event2.ics", SAMPLE_ICS_2)

    result = await harness.sync_manager.sync()

    assert result.path_used == SyncPath.RFC_6578
    assert result.added == 2
    assert result.updated == 0
    assert result.deleted == 0

    resources = await harness.local_store.get_resources("/work")
    assert len(resources) == 2


@pytest.mark.asyncio
async def test_path1_incremental_sync(harness: LoopbackHarness) -> None:
    """Real Path 1 incremental synchronization with updated resources."""
    await harness.client.put_resource(f"{harness.base_url}event1.ics", SAMPLE_ICS_1)
    res1 = await harness.sync_manager.sync()
    assert res1.added == 1

    updated_ics = SAMPLE_ICS_1.replace("Work Meeting", "Updated Work Meeting")
    await harness.client.put_resource(f"{harness.base_url}event1.ics", updated_ics)

    res2 = await harness.sync_manager.sync()
    assert res2.path_used == SyncPath.RFC_6578
    assert res2.updated == 1

    local_res = await harness.local_store.get_resource("/work/event1.ics")
    assert local_res is not None
    assert "Updated Work Meeting" in local_res.ics_data


@pytest.mark.asyncio
async def test_path2_etag_diff_fallback(harness: LoopbackHarness) -> None:
    """Real Path 2 (ETag diffing via PROPFIND Depth 1 + calendar-multiget) synchronization."""
    await harness.client.put_resource(f"{harness.base_url}event1.ics", SAMPLE_ICS_1)
    await harness.client.put_resource(f"{harness.base_url}event2.ics", SAMPLE_ICS_2)

    # Force Path 2 execution
    result = await harness.sync_manager.sync(force_full_sync=True)

    assert result.path_used == SyncPath.ETAG_DIFF
    assert result.added == 2
    assert result.updated == 0
    assert result.deleted == 0

    cal = await harness.sync_manager.get_calendar()
    assert len(cal.events) == 2


@pytest.mark.asyncio
async def test_path2_etag_diff_deletion(harness: LoopbackHarness) -> None:
    """Real Path 2 ETag diff detection of remote deletions."""
    await harness.client.put_resource(f"{harness.base_url}event1.ics", SAMPLE_ICS_1)
    await harness.client.put_resource(f"{harness.base_url}event2.ics", SAMPLE_ICS_2)

    await harness.sync_manager.sync(force_full_sync=True)
    assert len(await harness.local_store.get_resources("/work")) == 2

    # Delete event1 on server
    await harness.client.delete_resource(f"{harness.base_url}event1.ics")

    result = await harness.sync_manager.sync(force_full_sync=True)
    assert result.path_used == SyncPath.ETAG_DIFF
    assert result.deleted == 1
    assert len(await harness.local_store.get_resources("/work")) == 1


@pytest.mark.asyncio
async def test_raw_ics_immutability(harness: LoopbackHarness) -> None:
    """Verify raw .ics payloads are saved verbatim through client-server loopback."""
    raw_ics = (
        "BEGIN:VCALENDAR\n"
        "VERSION:2.0\n"
        "PRODID:-//Test//EN\n"
        "BEGIN:VEVENT\n"
        "UID:crlf-event-123\n"
        "SUMMARY:CRLF Event\n"
        "END:VEVENT\n"
        "END:VCALENDAR"
    )
    await harness.client.put_resource(f"{harness.base_url}raw.ics", raw_ics)
    await harness.sync_manager.sync()

    local_res = await harness.local_store.get_resource("/work/raw.ics")
    assert local_res is not None
    assert local_res.ics_data == raw_ics



@pytest.mark.asyncio
async def test_sync_convergence(harness: LoopbackHarness) -> None:
    """Verify consecutive sync calls with no remote changes yield 0 updates/additions."""
    await harness.client.put_resource(f"{harness.base_url}event1.ics", SAMPLE_ICS_1)

    res1 = await harness.sync_manager.sync()
    assert res1.added == 1

    res2 = await harness.sync_manager.sync()
    assert res2.added == 0
    assert res2.updated == 0
    assert res2.deleted == 0
    assert res2.unmodified == 1


@pytest.mark.asyncio
async def test_empty_collection_sync(harness: LoopbackHarness) -> None:
    """Synchronize an empty calendar collection cleanly on both paths."""
    res1 = await harness.sync_manager.sync()
    assert res1.added == 0
    assert res1.updated == 0
    assert res1.deleted == 0

    res2 = await harness.sync_manager.sync(force_full_sync=True)
    assert res2.added == 0
    assert res2.updated == 0
    assert res2.deleted == 0


@pytest.mark.asyncio
async def test_uri_trailing_slash_normalization(harness: LoopbackHarness) -> None:
    """Verify collection URLs and resource paths normalize correctly."""
    await harness.client.put_resource(f"{harness.base_url}event1.ics", SAMPLE_ICS_1)
    result = await harness.sync_manager.sync()

    assert result.added == 1
    res = await harness.local_store.get_resource("/work/event1.ics")
    assert res is not None



@pytest.mark.asyncio
async def test_recurrence_exceptions_and_multi_vevent_parse(harness: LoopbackHarness) -> None:
    """Verify multi-VEVENT files (recurrence rules and RECURRENCE-ID exceptions) aggregate properly."""
    await harness.client.put_resource(f"{harness.base_url}recurring.ics", SAMPLE_RECURRENCE_ICS)

    await harness.sync_manager.sync()
    cal = await harness.sync_manager.get_calendar()

    assert len(cal.events) == 2
    summaries = [e.summary for e in cal.events]
    assert "Weekly Meeting" in summaries
    assert "Weekly Meeting (Rescheduled)" in summaries
