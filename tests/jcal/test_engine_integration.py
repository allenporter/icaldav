"""Integration tests proving CoreWebDavEngine domain isolation with alternative jCal serializer."""

import pytest

from icaldav.engine.core import CoreWebDavEngine
from icaldav.engine.models import CalendarQuery, PropertyTag, PropfindQuery
from icaldav.filter import CompFilter
from icaldav.jcal import JCalSerializer
from icaldav.store.memory import MemoryStore
from icaldav.store.principal import InMemoryPrincipalStore
from icaldav.store.types import CalendarResource, CollectionPath, ResourcePath
from icaldav.xml.namespaces import CALDAV, DAV


@pytest.fixture
def test_setup() -> tuple[MemoryStore, InMemoryPrincipalStore, CoreWebDavEngine]:
    store = MemoryStore()
    p_store = InMemoryPrincipalStore()
    engine = CoreWebDavEngine()
    return store, p_store, engine


async def test_jcal_propfind_pluggable_pipeline(
    test_setup: tuple[MemoryStore, InMemoryPrincipalStore, CoreWebDavEngine],
) -> None:
    """Test end-to-end PROPFIND flow: JSON payload -> Request IR -> Engine -> Response IR -> JSON MultiStatus."""
    store, p_store, engine = test_setup

    # 1. Simulate incoming JSON PROPFIND request
    req_json = JCalSerializer.serialize_propfind_request(
        [
            PropertyTag(DAV, "resourcetype"),
            PropertyTag(DAV, "displayname"),
            PropertyTag(DAV, "current-user-principal"),
        ]
    )

    # 2. Decode wire JSON request into domain Request IR
    props = JCalSerializer.deserialize_propfind_request(req_json)
    query = PropfindQuery(
        href="/principals/users/user/",
        depth=0,
        requested_props=props,
        user_id="user",
    )

    # 3. Evaluate query in pure domain CoreWebDavEngine (zero HTTP / zero XML)
    ir_multistatus = await engine.evaluate_propfind(store, p_store, query)

    # 4. Serialize Response IR into target jCal / JSON wire format
    resp_json = JCalSerializer.serialize_multistatus(ir_multistatus)

    # 5. Verify serialized payload
    parsed = JCalSerializer.deserialize_multistatus(resp_json)
    assert len(parsed.responses) == 1
    resp = parsed.responses[0]
    assert resp.href == "/principals/users/user/"
    p200 = next(b for b in resp.propstats if b.status_code == 200)
    assert PropertyTag(DAV, "current-user-principal") in p200.properties


async def test_jcal_calendar_query_pipeline(
    test_setup: tuple[MemoryStore, InMemoryPrincipalStore, CoreWebDavEngine],
) -> None:
    """Test end-to-end Calendar Query flow: JSON payload -> Request IR -> Engine -> Response IR -> jCal JSON."""
    store, _p_store, engine = test_setup

    # Populate store with an event
    coll = CollectionPath.parse("/work/")
    event_ics = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Test//EN\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:event-101\r\n"
        "SUMMARY:Pluggable Serializer Workshop\r\n"
        "DTSTART:20260817T140000Z\r\n"
        "DTEND:20260817T150000Z\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR"
    )

    await store.save_resource(
        CalendarResource(
            path=ResourcePath.parse("/work/event-101.ics"),
            ics_data=event_ics,
            etag='"etag-101"',
        )
    )

    # 1. Wire JSON query for VEVENT components with calendar-data
    wire_query = CalendarQuery(
        comp_filter=CompFilter(
            name="VCALENDAR",
            comp_filters=[CompFilter(name="VEVENT")],
        ),
        props=[
            PropertyTag(DAV, "getetag"),
            PropertyTag(CALDAV, "calendar-data"),
        ],
    )
    json_req = JCalSerializer.serialize_calendar_query(wire_query)

    # 2. Decode wire request into Request IR
    query_ir = JCalSerializer.deserialize_calendar_query(json_req)

    # 3. Pure Engine Evaluation
    report_ir = await engine.evaluate_calendar_query(store, coll, query_ir)

    # 4. Encode Response IR into wire jCal response
    json_resp = JCalSerializer.serialize_report_response(
        report_ir, convert_ics_to_jcal=True
    )

    # 5. Verify wire response contains RFC 7265 jCal structure
    restored = JCalSerializer.deserialize_report_response(json_resp)
    assert len(restored.responses) == 1
    assert restored.responses[0].href == "/work/event-101.ics"
    assert restored.responses[0].ics_data is not None
    assert "Pluggable Serializer Workshop" in restored.responses[0].ics_data
