"""Normative compliance test suite for RFC 4791 (CalDAV: Calendaring Extensions to WebDAV)."""

import pytest

from tests.compliance.conftest import ComplianceHarness

SAMPLE_EVENT_JULY = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//Example Corp.//EN\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:event-july-2026\r\n"
    "SUMMARY:July Planning Meeting\r\n"
    "DTSTART:20260715T100000Z\r\n"
    "DTEND:20260715T110000Z\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR"
)

SAMPLE_EVENT_AUGUST = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//Example Corp.//EN\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:event-august-2026\r\n"
    "SUMMARY:August Retrospective\r\n"
    "DTSTART:20260820T140000Z\r\n"
    "DTEND:20260820T150000Z\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR"
)

SAMPLE_TODO = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//Example Corp.//EN\r\n"
    "BEGIN:VTODO\r\n"
    "UID:todo-task-1\r\n"
    "SUMMARY:File compliance report\r\n"
    "END:VTODO\r\n"
    "END:VCALENDAR"
)


@pytest.mark.asyncio
async def test_rfc4791_options_calendar_access(harness: ComplianceHarness) -> None:
    """RFC 4791 §5.1: Must advertise 'calendar-access' in DAV OPTIONS header."""
    resp = await harness.test_client.options("/")
    assert resp.status == 200
    dav_header = resp.headers.get("DAV", "")
    assert "calendar-access" in dav_header
    assert "1" in dav_header


@pytest.mark.asyncio
async def test_rfc4791_mkcalendar_lifecycle(harness: ComplianceHarness) -> None:
    """RFC 4791 §5.3.1: MKCALENDAR creates calendar collection; duplicate returns 405."""
    # 1. MKCALENDAR creates new collection
    resp = await harness.test_client.request("MKCALENDAR", "/team-calendar")
    assert resp.status == 201

    # 2. MKCALENDAR on existing collection returns 405 Method Not Allowed
    dup_resp = await harness.test_client.request("MKCALENDAR", "/team-calendar")
    assert dup_resp.status == 405

    # 3. PROPFIND verifies collection and calendar resource types
    items = await harness.client.propfind(f"{harness.base_url}team-calendar/", depth=0)
    assert len(items) == 1
    assert items[0].is_collection is True
    assert items[0].is_calendar is True


@pytest.mark.asyncio
async def test_rfc4791_calendar_properties(harness: ComplianceHarness) -> None:
    """RFC 4791 §5.2.3 - §5.2.5: Advertise supported components, data format, and max size."""
    await harness.test_client.request("MKCALENDAR", "/props-test")
    items = await harness.client.propfind(
        f"{harness.base_url}props-test/",
        depth=0,
        props=[
            "supported-calendar-component-set",
            "supported-calendar-data",
            "max-resource-size",
        ],
    )
    assert len(items) == 1


@pytest.mark.asyncio
async def test_rfc4791_calendar_query_component_filtering(
    harness: ComplianceHarness,
) -> None:
    """RFC 4791 §7.8: calendar-query REPORT filters resources by component type."""
    cal_url = f"{harness.base_url}query-cal"
    await harness.test_client.request("MKCALENDAR", "/query-cal")

    # Put VEVENT and VTODO
    await harness.client.put_resource(f"{cal_url}/event.ics", SAMPLE_EVENT_JULY)
    await harness.client.put_resource(f"{cal_url}/todo.ics", SAMPLE_TODO)

    # 1. Query for VEVENT only
    events = await harness.client.calendar_query(cal_url, component="VEVENT")
    assert len(events) == 1
    assert events[0].href == "/query-cal/event.ics"
    assert "July Planning" in (events[0].ics_data or "")

    # 2. Query for VTODO only
    todos = await harness.client.calendar_query(cal_url, component="VTODO")
    assert len(todos) == 1
    assert todos[0].href == "/query-cal/todo.ics"
    assert "File compliance" in (todos[0].ics_data or "")

    # 3. Query for non-existent component (VJOURNAL) returns empty list
    journals = await harness.client.calendar_query(cal_url, component="VJOURNAL")
    assert len(journals) == 0


@pytest.mark.asyncio
async def test_rfc4791_calendar_query_time_range(
    harness: ComplianceHarness,
) -> None:
    """RFC 4791 §7.8: calendar-query REPORT filters resources by time range."""
    cal_url = f"{harness.base_url}timerange-cal"
    await harness.test_client.request("MKCALENDAR", "/timerange-cal")

    await harness.client.put_resource(f"{cal_url}/july.ics", SAMPLE_EVENT_JULY)
    await harness.client.put_resource(f"{cal_url}/august.ics", SAMPLE_EVENT_AUGUST)

    # Query for July 2026 only
    july_events = await harness.client.calendar_query(
        cal_url,
        component="VEVENT",
        time_start="20260701T000000Z",
        time_end="20260801T000000Z",
    )
    assert len(july_events) == 1
    assert july_events[0].href == "/timerange-cal/july.ics"

    # Query for August 2026 only
    august_events = await harness.client.calendar_query(
        cal_url,
        component="VEVENT",
        time_start="20260801T000000Z",
        time_end="20260901T000000Z",
    )
    assert len(august_events) == 1
    assert august_events[0].href == "/timerange-cal/august.ics"


@pytest.mark.asyncio
async def test_rfc4791_calendar_multiget(harness: ComplianceHarness) -> None:
    """RFC 4791 §7.9: calendar-multiget REPORT retrieves multiple specific resources."""
    cal_url = f"{harness.base_url}multiget-cal"
    await harness.test_client.request("MKCALENDAR", "/multiget-cal")

    await harness.client.put_resource(f"{cal_url}/july.ics", SAMPLE_EVENT_JULY)
    await harness.client.put_resource(f"{cal_url}/august.ics", SAMPLE_EVENT_AUGUST)

    # Batch multiget with 1 valid and 1 missing resource
    results = await harness.client.calendar_multiget(
        cal_url,
        hrefs=["/multiget-cal/july.ics", "/multiget-cal/nonexistent.ics"],
    )
    assert len(results) == 1
    assert results[0].href == "/multiget-cal/july.ics"
    assert results[0].etag != ""
    assert results[0].ics_data is not None
