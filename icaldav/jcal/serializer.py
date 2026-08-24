"""Unified jCal / JSON Serializer implementation for WebDAV / CalDAV IR models.

Demonstrates pluggable wire-format serialization without touching CoreWebDavEngine
domain logic or storage layers.

RFC References:
    - RFC 4918: WebDAV Core
    - RFC 4791: CalDAV Core
    - RFC 6578: Collection Synchronization
    - RFC 7265: jCal: The JSON Format for iCalendar
"""

from typing import Any

from icaldav.engine.models import (
    CalendarMultigetQuery,
    CalendarQuery,
    PrincipalSearchQuery,
    PropertyTag,
    ReportMultiStatus,
    SyncCollectionQuery,
    WebDavMultiStatus,
)
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
)


class JCalSerializer:
    """Pluggable JSON / jCal serializer for WebDAV and CalDAV operations."""

    content_type: str = "application/calendar+json"

    @staticmethod
    def encode_ics_to_jcal(ics_text: str) -> list[Any]:
        """Convert RFC 5545 iCalendar string to RFC 7265 jCal JSON array."""
        return ics_to_jcal(ics_text)

    @staticmethod
    def decode_jcal_to_ics(jcal_comp: list[Any]) -> str:
        """Convert RFC 7265 jCal JSON array to RFC 5545 iCalendar string."""
        return jcal_to_ics(jcal_comp)

    @staticmethod
    def serialize_propfind_request(
        props: list[PropertyTag | str] | None = None,
    ) -> bytes:
        """Serialize a PROPFIND requested property list into JSON bytes."""
        return build_propfind_request_json(props)

    @staticmethod
    def deserialize_propfind_request(
        data: bytes | str | dict[str, Any],
    ) -> list[PropertyTag] | None:
        """Deserialize a JSON PROPFIND request into list of PropertyTags or None."""
        return parse_propfind_request_json(data)

    @staticmethod
    def serialize_multistatus(
        multistatus: WebDavMultiStatus, convert_calendar_data: bool = True
    ) -> bytes:
        """Serialize a WebDavMultiStatus IR object to JSON bytes."""
        return build_multistatus_json(
            multistatus, convert_calendar_data=convert_calendar_data
        )

    @staticmethod
    def deserialize_multistatus(
        data: bytes | str | dict[str, Any],
    ) -> WebDavMultiStatus:
        """Deserialize JSON bytes to a WebDavMultiStatus IR object."""
        return parse_multistatus_json(data)

    @staticmethod
    def serialize_calendar_query(query: CalendarQuery) -> bytes:
        """Serialize a CalendarQuery IR object to JSON bytes."""
        return build_calendar_query_json(query)

    @staticmethod
    def deserialize_calendar_query(
        data: bytes | str | dict[str, Any],
    ) -> CalendarQuery:
        """Deserialize JSON bytes to a CalendarQuery IR object."""
        return parse_calendar_query_json(data)

    @staticmethod
    def serialize_calendar_multiget(query: CalendarMultigetQuery) -> bytes:
        """Serialize a CalendarMultigetQuery IR object to JSON bytes."""
        return build_calendar_multiget_json(query)

    @staticmethod
    def deserialize_calendar_multiget(
        data: bytes | str | dict[str, Any],
    ) -> CalendarMultigetQuery:
        """Deserialize JSON bytes to a CalendarMultigetQuery IR object."""
        return parse_calendar_multiget_json(data)

    @staticmethod
    def serialize_sync_collection(query: SyncCollectionQuery) -> bytes:
        """Serialize a SyncCollectionQuery IR object to JSON bytes."""
        return build_sync_collection_json(query)

    @staticmethod
    def deserialize_sync_collection(
        data: bytes | str | dict[str, Any],
    ) -> SyncCollectionQuery:
        """Deserialize JSON bytes to a SyncCollectionQuery IR object."""
        return parse_sync_collection_json(data)

    @staticmethod
    def serialize_principal_search(query: PrincipalSearchQuery) -> bytes:
        """Serialize a PrincipalSearchQuery IR object to JSON bytes."""
        return build_principal_search_json(query)

    @staticmethod
    def deserialize_principal_search(
        data: bytes | str | dict[str, Any],
    ) -> PrincipalSearchQuery:
        """Deserialize JSON bytes to a PrincipalSearchQuery IR object."""
        return parse_principal_search_json(data)

    @staticmethod
    def serialize_report_response(
        status: ReportMultiStatus, convert_ics_to_jcal: bool = True
    ) -> bytes:
        """Serialize a ReportMultiStatus IR object to JSON bytes."""
        return build_report_response_json(
            status, convert_ics_to_jcal=convert_ics_to_jcal
        )

    @staticmethod
    def deserialize_report_response(
        data: bytes | str | dict[str, Any],
    ) -> ReportMultiStatus:
        """Deserialize JSON bytes to a ReportMultiStatus IR object."""
        return parse_report_response_json(data)
