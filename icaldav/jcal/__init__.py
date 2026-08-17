"""jCal (RFC 7265) and JSON wire-format encoders and decoders for icaldav.

Enables pluggable JSON serialization for WebDAV/CalDAV IR dataclasses without
altering CoreWebDavEngine domain logic or storage layers.

RFC References:
    - RFC 7265: jCal: The JSON Format for iCalendar
    - RFC 4918: WebDAV Core
    - RFC 4791: CalDAV Core
    - RFC 6578: Collection Synchronization
"""

from icaldav.jcal.codec import ics_to_jcal, jcal_to_ics
from icaldav.jcal.propfind import (
    build_multistatus_json,
    build_propfind_request_json,
    parse_multistatus_json,
    parse_propfind_request_json,
)
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
    parse_sync_collection_response_json,
)
from icaldav.jcal.serializer import JCalSerializer

__all__ = [
    "JCalSerializer",
    "build_calendar_multiget_json",
    "build_calendar_query_json",
    "build_multistatus_json",
    "build_principal_search_json",
    "build_propfind_request_json",
    "build_report_response_json",
    "build_sync_collection_json",
    "ics_to_jcal",
    "jcal_to_ics",
    "parse_calendar_multiget_json",
    "parse_calendar_query_json",
    "parse_multistatus_json",
    "parse_principal_search_json",
    "parse_propfind_request_json",
    "parse_report_response_json",
    "parse_sync_collection_json",
    "parse_sync_collection_response_json",
]
