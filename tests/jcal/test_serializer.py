"""Unit tests for unified JCalSerializer facade."""

import json

from icaldav.engine.models import (
    CalendarMultigetQuery,
    CalendarQuery,
    PrincipalSearchQuery,
    PropertyTag,
    PropstatBlock,
    ReportMultiStatus,
    ReportResource,
    SearchCriteria,
    SyncCollectionQuery,
    WebDavMultiStatus,
    WebDavResourceStatus,
)
from icaldav.filter import CompFilter, TimeRange
from icaldav.jcal.serializer import JCalSerializer
from icaldav.xml.namespaces import CALDAV, DAV

SAMPLE_ICS = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//Test//EN\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:evt-serializer-1\r\n"
    "SUMMARY:Facade Test\r\n"
    "DTSTART:20260817T120000Z\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR"
)


def test_serializer_metadata() -> None:
    """Verify serializer content type metadata."""
    assert JCalSerializer.content_type == "application/calendar+json"


def test_serializer_codec_roundtrip() -> None:
    """Verify encode_ics_to_jcal and decode_jcal_to_ics facade methods."""
    jcal = JCalSerializer.encode_ics_to_jcal(SAMPLE_ICS)
    assert isinstance(jcal, list)
    assert jcal[0] == "vcalendar"

    ics_out = JCalSerializer.decode_jcal_to_ics(jcal)
    assert "BEGIN:VCALENDAR" in ics_out
    assert "SUMMARY:Facade Test" in ics_out


def test_serializer_propfind_roundtrip() -> None:
    """Verify PROPFIND request and multistatus serialization via facade."""
    props = [PropertyTag(DAV, "getetag"), PropertyTag(DAV, "displayname")]
    req_bytes = JCalSerializer.serialize_propfind_request(props)
    parsed_props = JCalSerializer.deserialize_propfind_request(req_bytes)
    assert parsed_props == props

    multistatus = WebDavMultiStatus(
        responses=[
            WebDavResourceStatus(
                href="/work/test.ics",
                propstats=[
                    PropstatBlock(
                        status_code=200,
                        properties={
                            PropertyTag(DAV, "getetag"): '"etag-1"',
                            PropertyTag(CALDAV, "calendar-data"): SAMPLE_ICS,
                        },
                    )
                ],
            )
        ]
    )
    ms_bytes = JCalSerializer.serialize_multistatus(
        multistatus, convert_calendar_data=True
    )
    restored_ms = JCalSerializer.deserialize_multistatus(ms_bytes)
    assert len(restored_ms.responses) == 1
    assert restored_ms.responses[0].href == "/work/test.ics"


def test_serializer_calendar_query_roundtrip() -> None:
    """Verify CalendarQuery serialization via facade."""
    query = CalendarQuery(
        comp_filter=CompFilter(
            name="VCALENDAR",
            comp_filters=[CompFilter(name="VEVENT")],
        ),
        time_range=TimeRange(start="20260801T000000Z", end="20260831T235959Z"),
        props=[PropertyTag(DAV, "getetag")],
    )
    query_bytes = JCalSerializer.serialize_calendar_query(query)
    restored = JCalSerializer.deserialize_calendar_query(query_bytes)
    assert restored.comp_filter.name == "VCALENDAR"
    assert restored.time_range is not None
    assert restored.time_range.start == "20260801T000000Z"


def test_serializer_calendar_multiget_roundtrip() -> None:
    """Verify CalendarMultigetQuery serialization via facade."""
    query = CalendarMultigetQuery(
        hrefs=["/cal/1.ics", "/cal/2.ics"],
        props=[PropertyTag(DAV, "getetag"), PropertyTag(CALDAV, "calendar-data")],
    )
    bytes_data = JCalSerializer.serialize_calendar_multiget(query)
    restored = JCalSerializer.deserialize_calendar_multiget(bytes_data)
    assert restored.hrefs == ["/cal/1.ics", "/cal/2.ics"]
    assert len(restored.props) == 2


def test_serializer_sync_collection_roundtrip() -> None:
    """Verify SyncCollectionQuery serialization via facade."""
    query = SyncCollectionQuery(sync_token="sync-12345", limit=100)
    bytes_data = JCalSerializer.serialize_sync_collection(query)
    restored = JCalSerializer.deserialize_sync_collection(bytes_data)
    assert restored.sync_token == "sync-12345"
    assert restored.limit == 100


def test_serializer_principal_search_roundtrip() -> None:
    """Verify PrincipalSearchQuery serialization via facade."""
    query = PrincipalSearchQuery(
        criteria=[SearchCriteria(prop_tag="displayname", match="John")],
        props=[PropertyTag(DAV, "displayname")],
        user_id="john_doe",
    )
    bytes_data = JCalSerializer.serialize_principal_search(query)
    restored = JCalSerializer.deserialize_principal_search(bytes_data)
    assert len(restored.criteria) == 1
    assert restored.criteria[0].match == "John"
    assert restored.user_id == "john_doe"


def test_serializer_report_response_roundtrip() -> None:
    """Verify ReportMultiStatus serialization via facade."""
    report = ReportMultiStatus(
        responses=[
            ReportResource(
                href="/cal/1.ics",
                etag='"e1"',
                ics_data=SAMPLE_ICS,
            )
        ],
        missing_hrefs=["/cal/missing.ics"],
        deleted_hrefs=["/cal/deleted.ics"],
        sync_token="token-999",
    )
    report_bytes = JCalSerializer.serialize_report_response(
        report, convert_ics_to_jcal=True
    )
    restored = JCalSerializer.deserialize_report_response(report_bytes)
    assert restored.sync_token == "token-999"
    assert restored.missing_hrefs == ["/cal/missing.ics"]
    assert restored.deleted_hrefs == ["/cal/deleted.ics"]
    assert len(restored.responses) == 1
    assert restored.responses[0].href == "/cal/1.ics"
    assert restored.responses[0].ics_data is not None
    assert "Facade Test" in restored.responses[0].ics_data
