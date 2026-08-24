"""CalDAV REPORT JSON / jCal request and response codecs.

RFC References:
    - RFC 4791 Section 7.8: calendar-query REPORT
    - RFC 4791 Section 7.9: calendar-multiget REPORT
    - RFC 6578 Section 3: sync-collection REPORT
    - RFC 3744 Section 9.4: principal-property-search REPORT
    - RFC 7265: jCal: The JSON Format for iCalendar
"""

import json
from typing import Any

from icaldav.engine.models import (
    CalendarMultigetQuery,
    CalendarQuery,
    PrincipalSearchQuery,
    ReportMultiStatus,
    ReportResource,
    SearchCriteria,
    SyncCollectionQuery,
)
from icaldav.filter import CompFilter, TimeRange
from icaldav.jcal.codec import ics_to_jcal, jcal_to_ics
from icaldav.jcal.propfind import _parse_tag


def _comp_filter_to_dict(cf: CompFilter) -> dict[str, Any]:
    """Serialize a CompFilter domain object to dictionary."""
    res: dict[str, Any] = {"name": cf.name}
    if cf.time_range:
        tr_dict: dict[str, Any] = {}
        if cf.time_range.start:
            tr_dict["start"] = cf.time_range.start
        if cf.time_range.end:
            tr_dict["end"] = cf.time_range.end
        res["time_range"] = tr_dict
    if cf.comp_filters:
        res["comp_filters"] = [_comp_filter_to_dict(sub) for sub in cf.comp_filters]
    return res


def _dict_to_comp_filter(data: dict[str, Any]) -> CompFilter:
    """Deserialize a dictionary to a CompFilter domain object."""
    name = data.get("name", "VCALENDAR")
    tr: TimeRange | None = None
    if "time_range" in data and isinstance(data["time_range"], dict):
        tr_raw = data["time_range"]
        tr = TimeRange(start=tr_raw.get("start"), end=tr_raw.get("end"))

    subs: list[CompFilter] = []
    if "comp_filters" in data and isinstance(data["comp_filters"], list):
        subs = [_dict_to_comp_filter(sub_data) for sub_data in data["comp_filters"]]

    return CompFilter(name=name, time_range=tr, comp_filters=subs)


def build_calendar_query_json(query: CalendarQuery) -> bytes:
    """Serialize a CalendarQuery IR object to JSON bytes."""
    payload: dict[str, Any] = {
        "comp_filter": _comp_filter_to_dict(query.comp_filter),
        "props": [p.clark_name for p in query.props],
    }
    if query.time_range:
        tr_dict: dict[str, Any] = {}
        if query.time_range.start:
            tr_dict["start"] = query.time_range.start
        if query.time_range.end:
            tr_dict["end"] = query.time_range.end
        payload["time_range"] = tr_dict
    return json.dumps(payload, indent=2).encode("utf-8")


def parse_calendar_query_json(
    data: bytes | str | dict[str, Any],
) -> CalendarQuery:
    """Parse a JSON payload into a CalendarQuery IR object."""
    if isinstance(data, (bytes, str)):
        doc = json.loads(data)
    else:
        doc = data

    cf_data = doc.get("comp_filter", {"name": "VCALENDAR"})
    comp_filter = _dict_to_comp_filter(cf_data)

    tr: TimeRange | None = None
    if "time_range" in doc and isinstance(doc["time_range"], dict):
        tr_raw = doc["time_range"]
        tr = TimeRange(start=tr_raw.get("start"), end=tr_raw.get("end"))

    props = [_parse_tag(p) for p in doc.get("props", [])]
    return CalendarQuery(comp_filter=comp_filter, time_range=tr, props=props)


def build_calendar_multiget_json(query: CalendarMultigetQuery) -> bytes:
    """Serialize a CalendarMultigetQuery IR object to JSON bytes."""
    payload = {
        "hrefs": query.hrefs,
        "props": [p.clark_name for p in query.props],
    }
    return json.dumps(payload, indent=2).encode("utf-8")


def parse_calendar_multiget_json(
    data: bytes | str | dict[str, Any],
) -> CalendarMultigetQuery:
    """Parse a JSON payload into a CalendarMultigetQuery IR object."""
    if isinstance(data, (bytes, str)):
        doc = json.loads(data)
    else:
        doc = data

    hrefs = doc.get("hrefs", [])
    props = [_parse_tag(p) for p in doc.get("props", [])]
    return CalendarMultigetQuery(hrefs=hrefs, props=props)


def build_sync_collection_json(query: SyncCollectionQuery) -> bytes:
    """Serialize a SyncCollectionQuery IR object to JSON bytes."""
    payload: dict[str, Any] = {"sync_token": query.sync_token}
    if query.limit is not None:
        payload["limit"] = query.limit
    return json.dumps(payload, indent=2).encode("utf-8")


def parse_sync_collection_json(
    data: bytes | str | dict[str, Any],
) -> SyncCollectionQuery:
    """Parse a JSON payload into a SyncCollectionQuery IR object."""
    if isinstance(data, (bytes, str)):
        doc = json.loads(data)
    else:
        doc = data

    sync_token = doc.get("sync_token", "")
    limit = doc.get("limit")
    return SyncCollectionQuery(sync_token=sync_token, limit=limit)


def build_principal_search_json(query: PrincipalSearchQuery) -> bytes:
    """Serialize a PrincipalSearchQuery IR object to JSON bytes."""
    payload: dict[str, Any] = {
        "criteria": [
            {"prop_tag": c.prop_tag, "match": c.match} for c in query.criteria
        ],
        "props": [p.clark_name for p in query.props],
    }
    if query.user_id:
        payload["user_id"] = query.user_id
    return json.dumps(payload, indent=2).encode("utf-8")


def parse_principal_search_json(
    data: bytes | str | dict[str, Any],
) -> PrincipalSearchQuery:
    """Parse a JSON payload into a PrincipalSearchQuery IR object."""
    if isinstance(data, (bytes, str)):
        doc = json.loads(data)
    else:
        doc = data

    criteria = [
        SearchCriteria(prop_tag=c.get("prop_tag", ""), match=c.get("match", ""))
        for c in doc.get("criteria", [])
    ]
    props = [_parse_tag(p) for p in doc.get("props", [])]
    user_id = doc.get("user_id")
    return PrincipalSearchQuery(criteria=criteria, props=props, user_id=user_id)


def _format_report_resource_item(
    r: ReportResource, convert_ics_to_jcal: bool
) -> dict[str, Any]:
    """Format single ReportResource into dict entry."""
    clean_etag = f'"{r.etag.strip(chr(34))}"'
    item: dict[str, Any] = {
        "href": r.href,
        "etag": clean_etag,
        "status": 200,
    }
    if r.ics_data is not None:
        if convert_ics_to_jcal:
            try:
                item["jcal"] = ics_to_jcal(r.ics_data)
            except (ValueError, TypeError):
                item["calendar_data"] = r.ics_data
        else:
            item["calendar_data"] = r.ics_data
    return item


def build_report_response_json(
    resources: list[ReportResource] | ReportMultiStatus,
    missing_hrefs: list[str] | None = None,
    convert_ics_to_jcal: bool = True,
) -> bytes:
    """Serialize a ReportMultiStatus IR object to a JSON Multi-Status response body.

    Args:
        resources: Either ReportMultiStatus or list of ReportResource.
        missing_hrefs: Optional missing href list if passing a list of resources.
        convert_ics_to_jcal: If True, convert ics strings into RFC 7265 jCal structures.

    Returns:
        UTF-8 encoded JSON bytes.
    """
    if isinstance(resources, ReportMultiStatus):
        res_list = resources.responses
        missing_list = resources.missing_hrefs
        deleted_list = resources.deleted_hrefs
        sync_token = resources.sync_token
    else:
        res_list = resources
        missing_list = missing_hrefs or []
        deleted_list = []
        sync_token = None

    response_items = [
        _format_report_resource_item(r, convert_ics_to_jcal) for r in res_list
    ]

    payload: dict[str, Any] = {"responses": response_items}
    if missing_list:
        payload["missing_hrefs"] = missing_list
    if deleted_list:
        payload["deleted_hrefs"] = deleted_list
    if sync_token is not None:
        payload["sync_token"] = sync_token

    return json.dumps(payload, indent=2).encode("utf-8")


def parse_report_response_json(
    data: bytes | str | dict[str, Any],
) -> ReportMultiStatus:
    """Parse a JSON REPORT response body into a ReportMultiStatus IR object."""
    if isinstance(data, (bytes, str)):
        if not data:
            return ReportMultiStatus()
        doc = json.loads(data)
    else:
        doc = data

    responses: list[ReportResource] = []
    for item in doc.get("responses", []):
        href = item.get("href", "")
        etag = item.get("etag", "").strip('"')
        ics_data: str | None = None
        if "jcal" in item and isinstance(item["jcal"], list):
            ics_data = jcal_to_ics(item["jcal"])
        elif "calendar_data" in item and isinstance(item["calendar_data"], str):
            ics_data = item["calendar_data"]
        responses.append(ReportResource(href=href, etag=etag, ics_data=ics_data))

    missing_hrefs = doc.get("missing_hrefs", [])
    deleted_hrefs = doc.get("deleted_hrefs", [])
    sync_token = doc.get("sync_token")

    return ReportMultiStatus(
        responses=responses,
        missing_hrefs=missing_hrefs,
        deleted_hrefs=deleted_hrefs,
        sync_token=sync_token,
    )


def parse_sync_collection_response_json(
    data: bytes | str | dict[str, Any],
) -> tuple[list[ReportResource], str | None]:
    """Parse a JSON RFC 6578 sync-collection REPORT response.

    Returns:
        Tuple of (resources list, sync token).
    """
    status = parse_report_response_json(data)
    return status.responses, status.sync_token
