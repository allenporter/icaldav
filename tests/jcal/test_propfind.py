"""Unit tests for PROPFIND JSON / jCal request and response serialization."""

import json

from icaldav.engine.models import (
    PropertyTag,
    PropstatBlock,
    WebDavMultiStatus,
    WebDavResourceStatus,
)
from icaldav.jcal.propfind import (
    build_multistatus_json,
    build_propfind_request_json,
    parse_multistatus_json,
    parse_propfind_request_json,
)
from icaldav.xml.namespaces import CALDAV, DAV


def test_build_and_parse_propfind_request_allprop() -> None:
    """Verify allprop PROPFIND serialization."""
    data = build_propfind_request_json(None)
    doc = json.loads(data)
    assert doc == {"allprop": True}
    assert parse_propfind_request_json(data) is None


def test_build_and_parse_propfind_request_explicit() -> None:
    """Verify explicit property request serialization."""
    props = [
        PropertyTag(DAV, "getetag"),
        PropertyTag(DAV, "displayname"),
        PropertyTag(CALDAV, "calendar-data"),
    ]
    data = build_propfind_request_json(props)
    doc = json.loads(data)
    assert "props" in doc
    assert "{DAV:}getetag" in doc["props"]
    assert "{urn:ietf:params:xml:ns:caldav}calendar-data" in doc["props"]

    parsed = parse_propfind_request_json(data)
    assert parsed is not None
    assert len(parsed) == 3
    assert parsed[0] == PropertyTag(DAV, "getetag")
    assert parsed[1] == PropertyTag(DAV, "displayname")
    assert parsed[2] == PropertyTag(CALDAV, "calendar-data")


def test_build_and_parse_multistatus_json() -> None:
    """Verify WebDavMultiStatus serialization and deserialization with embedded jCal."""
    sample_ics = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Example//EN\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:item1\r\n"
        "SUMMARY:Meeting\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR"
    )

    multistatus = WebDavMultiStatus(
        responses=[
            WebDavResourceStatus(
                href="/work/event1.ics",
                propstats=[
                    PropstatBlock(
                        status_code=200,
                        properties={
                            PropertyTag(DAV, "getetag"): '"etag123"',
                            PropertyTag(DAV, "displayname"): "Meeting",
                            PropertyTag(CALDAV, "calendar-data"): sample_ics,
                        },
                    ),
                    PropstatBlock(
                        status_code=404,
                        properties={
                            PropertyTag(DAV, "sync-token"): "",
                        },
                    ),
                ],
            )
        ]
    )

    json_bytes = build_multistatus_json(multistatus, convert_calendar_data=True)
    doc = json.loads(json_bytes)

    assert "responses" in doc
    assert len(doc["responses"]) == 1
    resp = doc["responses"][0]
    assert resp["href"] == "/work/event1.ics"
    assert len(resp["propstats"]) == 2

    # Check 200 block with jCal
    block200 = next(b for b in resp["propstats"] if b["status"] == 200)
    cal_data = block200["properties"]["{urn:ietf:params:xml:ns:caldav}calendar-data"]
    assert isinstance(cal_data, list)
    assert cal_data[0] == "vcalendar"

    # Roundtrip back to IR WebDavMultiStatus
    parsed_ms = parse_multistatus_json(json_bytes)
    assert len(parsed_ms.responses) == 1
    assert parsed_ms.responses[0].href == "/work/event1.ics"
    assert len(parsed_ms.responses[0].propstats) == 2

    p200 = next(b for b in parsed_ms.responses[0].propstats if b.status_code == 200)
    assert p200.properties[PropertyTag(DAV, "getetag")] == '"etag123"'
    restored_ics = p200.properties[PropertyTag(CALDAV, "calendar-data")]
    assert "BEGIN:VCALENDAR" in restored_ics
    assert "SUMMARY:Meeting" in restored_ics


def test_parse_propfind_edge_cases() -> None:
    """Verify parse_propfind_request_json with empty/invalid/custom formats."""
    assert parse_propfind_request_json(b"") is None
    assert parse_propfind_request_json("   ") is None
    assert parse_propfind_request_json("{invalid_json}") is None
    assert parse_propfind_request_json(123) is None  # type: ignore[arg-type]

    # Bare array format
    bare_array = json.dumps(["{DAV:}getetag", "{DAV:}displayname"])
    res = parse_propfind_request_json(bare_array)
    assert res == [PropertyTag(DAV, "getetag"), PropertyTag(DAV, "displayname")]

    # Dict with object-style tag definitions
    obj_style = json.dumps(
        {
            "props": [
                {"namespace": "DAV:", "name": "resourcetype"},
                "displayname",
            ]
        }
    )
    res_obj = parse_propfind_request_json(obj_style)
    assert res_obj == [
        PropertyTag(DAV, "resourcetype"),
        PropertyTag(DAV, "displayname"),
    ]


def test_multistatus_json_without_conversion() -> None:
    """Verify WebDavMultiStatus without calendar-data jCal conversion."""
    sample_ics = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR"
    multistatus = WebDavMultiStatus(
        responses=[
            WebDavResourceStatus(
                href="/work/event.ics",
                propstats=[
                    PropstatBlock(
                        status_code=200,
                        properties={
                            PropertyTag(CALDAV, "calendar-data"): sample_ics,
                        },
                    )
                ],
            )
        ]
    )
    json_bytes = build_multistatus_json(multistatus, convert_calendar_data=False)
    doc = json.loads(json_bytes)
    prop_val = doc["responses"][0]["propstats"][0]["properties"][
        "{urn:ietf:params:xml:ns:caldav}calendar-data"
    ]
    assert isinstance(prop_val, str)
    assert "BEGIN:VCALENDAR" in prop_val
