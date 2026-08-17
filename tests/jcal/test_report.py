"""Unit tests for REPORT queries and responses in JSON / jCal format."""

import json

from icaldav.engine.models import (
    CalendarMultigetQuery,
    CalendarQuery,
    PrincipalSearchQuery,
    PropertyTag,
    ReportMultiStatus,
    ReportResource,
    SearchCriteria,
    SyncCollectionQuery,
)
from icaldav.filter import CompFilter, TimeRange
from icaldav.jcal.report import (
    build_calendar_multiget_json,
    build_calendar_query_json,
    build_principal_search_json,
    build_report_response_json,
    build_sync_collection_json,
    parse_calendar_multiget_json,
    parse_calendar_query_json,
    parse_principal_search_json,
    parse_report_response_json,
    parse_sync_collection_json,
)
from icaldav.xml.namespaces import CALDAV, DAV


def test_calendar_query_json_roundtrip() -> None:
    """Verify CalendarQuery serialization with CompFilter and TimeRange."""
    query = CalendarQuery(
        comp_filter=CompFilter(
            name="VCALENDAR",
            comp_filters=[
                CompFilter(
                    name="VEVENT",
                    time_range=TimeRange(
                        start="20260801T000000Z", end="20260901T000000Z"
                    ),
                )
            ],
        ),
        time_range=TimeRange(start="20260801T000000Z", end="20260901T000000Z"),
        props=[PropertyTag(DAV, "getetag"), PropertyTag(CALDAV, "calendar-data")],
    )

    data = build_calendar_query_json(query)
    doc = json.loads(data)
    assert doc["comp_filter"]["name"] == "VCALENDAR"
    assert len(doc["comp_filter"]["comp_filters"]) == 1
    assert (
        doc["comp_filter"]["comp_filters"][0]["time_range"]["start"]
        == "20260801T000000Z"
    )

    restored = parse_calendar_query_json(data)
    assert restored.comp_filter.name == "VCALENDAR"
    assert len(restored.comp_filter.comp_filters) == 1
    assert restored.comp_filter.comp_filters[0].name == "VEVENT"
    assert restored.comp_filter.comp_filters[0].time_range is not None
    assert restored.comp_filter.comp_filters[0].time_range.start == "20260801T000000Z"
    assert len(restored.props) == 2


def test_calendar_multiget_json_roundtrip() -> None:
    """Verify CalendarMultigetQuery serialization."""
    query = CalendarMultigetQuery(
        hrefs=["/work/item1.ics", "/work/item2.ics"],
        props=[PropertyTag(DAV, "getetag")],
    )
    data = build_calendar_multiget_json(query)
    restored = parse_calendar_multiget_json(data)
    assert restored.hrefs == ["/work/item1.ics", "/work/item2.ics"]
    assert len(restored.props) == 1
    assert restored.props[0] == PropertyTag(DAV, "getetag")


def test_sync_collection_json_roundtrip() -> None:
    """Verify SyncCollectionQuery serialization."""
    query = SyncCollectionQuery(sync_token="token-xyz", limit=50)
    data = build_sync_collection_json(query)
    restored = parse_sync_collection_json(data)
    assert restored.sync_token == "token-xyz"
    assert restored.limit == 50


def test_principal_search_json_roundtrip() -> None:
    """Verify PrincipalSearchQuery serialization."""
    query = PrincipalSearchQuery(
        criteria=[SearchCriteria(prop_tag="displayname", match="alice")],
        props=[PropertyTag(DAV, "displayname")],
        user_id="alice",
    )
    data = build_principal_search_json(query)
    restored = parse_principal_search_json(data)
    assert len(restored.criteria) == 1
    assert restored.criteria[0].match == "alice"
    assert restored.user_id == "alice"


def test_report_multi_status_json_roundtrip() -> None:
    """Verify ReportMultiStatus serialization with embedded jCal."""
    sample_ics = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Test//EN\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:rep-1\r\n"
        "SUMMARY:Report Event\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR"
    )
    status = ReportMultiStatus(
        responses=[
            ReportResource(
                href="/work/rep-1.ics", etag='"etag-rep"', ics_data=sample_ics
            )
        ],
        missing_hrefs=["/work/rep-2.ics"],
        deleted_hrefs=["/work/rep-3.ics"],
        sync_token="sync-token-999",
    )

    data = build_report_response_json(status, convert_ics_to_jcal=True)
    doc = json.loads(data)

    assert doc["sync_token"] == "sync-token-999"
    assert doc["missing_hrefs"] == ["/work/rep-2.ics"]
    assert doc["deleted_hrefs"] == ["/work/rep-3.ics"]
    assert len(doc["responses"]) == 1
    assert "jcal" in doc["responses"][0]

    restored = parse_report_response_json(data)
    assert restored.sync_token == "sync-token-999"
    assert restored.missing_hrefs == ["/work/rep-2.ics"]
    assert restored.deleted_hrefs == ["/work/rep-3.ics"]
    assert len(restored.responses) == 1
    assert restored.responses[0].href == "/work/rep-1.ics"
    assert restored.responses[0].ics_data is not None
    assert "BEGIN:VCALENDAR" in restored.responses[0].ics_data
