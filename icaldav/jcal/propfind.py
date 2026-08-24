"""WebDAV PROPFIND JSON / jCal request and response codecs.

RFC References:
    - RFC 4918 Section 9.1: PROPFIND Method
    - RFC 4918 Section 13: Multi-Status Response
    - RFC 7265: jCal: The JSON Format for iCalendar
"""

import json
import logging
from collections.abc import Sequence
from typing import Any

from icaldav.engine.models import (
    PropertyTag,
    PropstatBlock,
    WebDavMultiStatus,
    WebDavResourceStatus,
)
from icaldav.jcal.codec import ics_to_jcal, jcal_to_ics
from icaldav.xml.namespaces import CALDAV, DAV

_LOGGER = logging.getLogger(__name__)


def _parse_tag(item: PropertyTag | dict[str, str] | str) -> PropertyTag:
    """Parse a property tag from PropertyTag, dict, or string."""
    if isinstance(item, PropertyTag):
        return item
    if isinstance(item, dict):
        ns = item.get("namespace", DAV)
        name = item.get("name", "")
        return PropertyTag(ns, name)
    tag_str = str(item)
    if tag_str.startswith("{") and "}" in tag_str:
        ns_part, local_name = tag_str[1:].split("}", 1)
        return PropertyTag(ns_part, local_name)
    return PropertyTag(DAV, tag_str)


def build_propfind_request_json(
    props: Sequence[PropertyTag | str] | None = None,
) -> bytes:
    """Build a JSON representation of a PROPFIND request body.

    Args:
        props: Optional sequence of PropertyTag or Clark-notation / short property name strings.
            If None or empty, represents an allprop request.

    Returns:
        UTF-8 encoded JSON bytes.
    """
    if not props:
        payload = {"allprop": True}
    else:
        prop_list = [_parse_tag(p).clark_name for p in props]
        payload = {"props": prop_list}

    return json.dumps(payload, indent=2).encode("utf-8")


def parse_propfind_request_json(
    data: bytes | str | dict[str, Any],
) -> list[PropertyTag] | None:
    """Parse a JSON PROPFIND request body to extract requested PropertyTags.

    Args:
        data: JSON bytes, JSON string, or decoded dict/list.

    Returns:
        List of PropertyTag objects, or None if allprop or empty request.
    """
    if isinstance(data, (bytes, str)):
        if (
            not data
            or (isinstance(data, bytes) and not data.strip())
            or (isinstance(data, str) and not data.strip())
        ):
            return None
        try:
            doc = json.loads(data)
        except json.JSONDecodeError:
            _LOGGER.debug("Failed to decode JSON PROPFIND request", exc_info=True)
            return None
    else:
        doc = data

    if not isinstance(doc, dict):
        if isinstance(doc, list):
            return [_parse_tag(p) for p in doc]
        return None

    if doc.get("allprop"):
        return None

    props_raw = doc.get("props") or doc.get("prop")
    if props_raw and isinstance(props_raw, list):
        return [_parse_tag(p) for p in props_raw]

    return None


def _format_property_value(
    tag: PropertyTag, val: Any, convert_calendar_data: bool
) -> Any:
    """Format property value, converting ics string to jCal array if applicable."""
    if (
        convert_calendar_data
        and tag.namespace == CALDAV
        and tag.name == "calendar-data"
        and isinstance(val, str)
    ):
        try:
            return ics_to_jcal(val)
        except (ValueError, TypeError):
            return val
    return val


def build_multistatus_json(
    multistatus: WebDavMultiStatus, convert_calendar_data: bool = True
) -> bytes:
    """Build a JSON Multi-Status response payload from a WebDavMultiStatus IR object.

    Args:
        multistatus: WebDavMultiStatus domain object.
        convert_calendar_data: Whether to convert embedded iCalendar (.ics) strings to RFC 7265 jCal structures.

    Returns:
        UTF-8 encoded JSON bytes.
    """
    response_list: list[dict[str, Any]] = []
    for resp in multistatus.responses:
        propstat_list: list[dict[str, Any]] = []
        for block in resp.propstats:
            props_dict: dict[str, Any] = {}
            for tag, val in block.properties.items():
                formatted_val = _format_property_value(tag, val, convert_calendar_data)
                props_dict[tag.clark_name] = formatted_val

            status_text = (
                f"HTTP/1.1 {block.status_code} "
                f"{'OK' if block.status_code == 200 else 'Not Found'}"
            )
            propstat_list.append(
                {
                    "status": block.status_code,
                    "status_text": status_text,
                    "properties": props_dict,
                }
            )

        response_list.append(
            {
                "href": resp.href,
                "propstats": propstat_list,
            }
        )

    payload = {"responses": response_list}
    return json.dumps(payload, indent=2).encode("utf-8")


def parse_multistatus_json(
    data: bytes | str | dict[str, Any],
) -> WebDavMultiStatus:
    """Parse a JSON Multi-Status response body into a WebDavMultiStatus IR object.

    Args:
        data: JSON bytes, JSON string, or parsed dictionary.

    Returns:
        WebDavMultiStatus IR object.
    """
    if isinstance(data, (bytes, str)):
        if not data:
            return WebDavMultiStatus()
        doc = json.loads(data)
    else:
        doc = data

    responses: list[WebDavResourceStatus] = []
    for resp_data in doc.get("responses", []):
        href = resp_data.get("href", "")
        propstats: list[PropstatBlock] = []
        for block_data in resp_data.get("propstats", []):
            status_code = block_data.get("status", 200)
            props_raw = block_data.get("properties", {})
            props: dict[PropertyTag, Any] = {}
            for k, v in props_raw.items():
                tag = _parse_tag(k)
                if (
                    tag.namespace == CALDAV
                    and tag.name == "calendar-data"
                    and isinstance(v, list)
                ):
                    v = jcal_to_ics(v)
                props[tag] = v
            propstats.append(PropstatBlock(status_code=status_code, properties=props))
        responses.append(WebDavResourceStatus(href=href, propstats=propstats))

    return WebDavMultiStatus(responses=responses)
