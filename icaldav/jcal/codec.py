"""jCal (RFC 7265) codec for iCalendar (RFC 5545) conversion.

Provides bidirectional conversion between RFC 5545 iCalendar text representation
and RFC 7265 jCal JSON representation.

RFC References:
    - RFC 5545: Internet Calendaring and Scheduling Core Object Specification (iCalendar)
    - RFC 7265: jCal: The JSON Format for iCalendar
"""

from collections.abc import Callable
import re
from typing import Any

type JCalRecur = dict[str, str | int | list[int] | list[str]]
type JCalScalar = str | int | float | list[float] | bool | JCalRecur

# Default property value types according to RFC 7265 Section 3.5 & RFC 5545
PROPERTY_TYPES: dict[str, str] = {
    "calscale": "text",
    "method": "text",
    "prodid": "text",
    "version": "text",
    "attach": "uri",
    "categories": "text",
    "class": "text",
    "comment": "text",
    "description": "text",
    "geo": "float",
    "location": "text",
    "percent-complete": "integer",
    "priority": "integer",
    "resources": "text",
    "status": "text",
    "summary": "text",
    "completed": "date-time",
    "dtend": "date-time",
    "due": "date-time",
    "dtstart": "date-time",
    "duration": "duration",
    "freebusy": "period",
    "transp": "text",
    "tzid": "text",
    "tzname": "text",
    "tzoffsetfrom": "utc-offset",
    "tzoffsetto": "utc-offset",
    "tzurl": "uri",
    "attendee": "cal-address",
    "contact": "text",
    "organizer": "cal-address",
    "recurrence-id": "date-time",
    "related-to": "text",
    "url": "uri",
    "uid": "text",
    "exdate": "date-time",
    "rdate": "date-time",
    "rrule": "recur",
    "action": "text",
    "repeat": "integer",
    "trigger": "duration",
    "created": "date-time",
    "dtstamp": "date-time",
    "last-modified": "date-time",
    "sequence": "integer",
    "request-status": "text",
}

MULTI_VALUED_PROPERTIES = {"categories", "resources", "exdate", "rdate"}


def _unescape_text(text: str) -> str:
    """Unescape iCalendar text special character sequences (RFC 5545 §3.3.11)."""
    result: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            if nxt in ("n", "N"):
                result.append("\n")
            elif nxt in (",", ";", "\\"):
                result.append(nxt)
            else:
                result.append(nxt)
            i += 2
        else:
            result.append(text[i])
            i += 1
    return "".join(result)


def _escape_text(text: str) -> str:
    """Escape text special character sequences for iCalendar (RFC 5545 §3.3.11)."""
    escaped = text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return escaped.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")


def _format_iso_datetime(val: str) -> str:
    """Convert RFC 5545 date/time/date-time to RFC 7265 ISO format."""
    v = val.strip()
    if "T" in v:
        date_part, time_part = v.split("T", 1)
        formatted_date = (
            f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}"
            if len(date_part) == 8
            else date_part
        )
        z_suffix = "Z" if time_part.endswith("Z") else ""
        raw_time = time_part[:-1] if z_suffix else time_part
        if len(raw_time) == 6:
            formatted_time = f"{raw_time[:2]}:{raw_time[2:4]}:{raw_time[4:6]}"
        elif len(raw_time) == 4:
            formatted_time = f"{raw_time[:2]}:{raw_time[2:4]}:00"
        else:
            formatted_time = raw_time
        return f"{formatted_date}T{formatted_time}{z_suffix}"
    if len(v) == 8 and v.isdigit():
        return f"{v[:4]}-{v[4:6]}-{v[6:8]}"
    return v


def _parse_iso_datetime_to_ics(val: str) -> str:
    """Convert RFC 7265 ISO date/time/date-time back to RFC 5545 format."""
    v = val.strip()
    if "T" in v:
        date_part, time_part = v.split("T", 1)
        clean_date = date_part.replace("-", "")
        clean_time = time_part.replace(":", "")
        return f"{clean_date}T{clean_time}"
    if "-" in v:
        return v.replace("-", "")
    return v


def _format_utc_offset(val: str) -> str:
    """Convert RFC 5545 offset (+0500) to RFC 7265 offset (+05:00)."""
    v = val.strip()
    if len(v) == 5 and (v[0] in ("+", "-")):
        return f"{v[:3]}:{v[3:]}"
    return v


def _parse_utc_offset_to_ics(val: str) -> str:
    """Convert RFC 7265 offset (+05:00) to RFC 5545 offset (+0500)."""
    return val.replace(":", "").strip()


def _parse_int_val(v: str) -> int:
    """Parse an iCalendar integer string to int."""
    return int(v.strip())


def _parse_float_val(v: str) -> float | list[float]:
    """Parse an iCalendar float string or semicolon-separated float pair (e.g. GEO)."""
    v_clean = v.strip()
    if ";" in v_clean:
        return [float(part.strip()) for part in v_clean.split(";") if part.strip()]
    return float(v_clean)


def _parse_int_list(v: str) -> list[int] | int:
    """Parse comma-separated integer list into list[int] or single int."""
    items = [int(item.strip()) for item in v.split(",") if item.strip()]
    if len(items) == 1:
        return items[0]
    return items


def _parse_recur_field(k_lower: str, v: str) -> str | int | list[int] | list[str]:
    """Parse single recurrence rule part into jCal type."""
    if k_lower in ("freq", "wkst"):
        return v.upper()
    if k_lower in ("count", "interval"):
        return _parse_int_val(v)
    if k_lower == "until":
        return _format_iso_datetime(v)
    if k_lower in (
        "bysecond",
        "byminute",
        "byhour",
        "bymonthday",
        "byyearday",
        "byweekno",
        "bymonth",
        "bysetpos",
    ):
        return _parse_int_list(v)
    if k_lower == "byday":
        days = [d.strip() for d in v.split(",") if d.strip()]
        return days if len(days) > 1 else days[0]
    return v


def _format_recur_to_jcal(val: str) -> JCalRecur:
    """Convert RFC 5545 RRULE string to RFC 7265 JSON recur object."""
    rule_dict: JCalRecur = {}
    for part in val.split(";"):
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        k_lower = k.lower()
        rule_dict[k_lower] = _parse_recur_field(k_lower, v)
    return rule_dict


def _format_recur_subparts(val: JCalRecur) -> list[str]:
    """Format non-standard recurrence subparts."""
    parts: list[str] = []
    for k, v in val.items():
        if k in ("freq", "until", "count", "interval"):
            continue
        k_upper = k.upper()
        if isinstance(v, list):
            joined = ",".join(str(item) for item in v)
            parts.append(f"{k_upper}={joined}")
        else:
            parts.append(f"{k_upper}={v}")
    return parts


def _format_recur_to_ics(val: JCalRecur | str) -> str:
    """Convert RFC 7265 recur object back to RFC 5545 RRULE string."""
    if isinstance(val, str):
        return val
    parts: list[str] = []
    if "freq" in val:
        parts.append(f"FREQ={str(val['freq']).upper()}")
    if "until" in val:
        parts.append(f"UNTIL={_parse_iso_datetime_to_ics(str(val['until']))}")
    if "count" in val:
        parts.append(f"COUNT={val['count']}")
    if "interval" in val:
        parts.append(f"INTERVAL={val['interval']}")
    parts.extend(_format_recur_subparts(val))
    return ";".join(parts)


CONVERTERS_TO_JCAL: dict[str, Callable[[str], JCalScalar]] = {
    "text": _unescape_text,
    "date-time": _format_iso_datetime,
    "date": _format_iso_datetime,
    "time": _format_iso_datetime,
    "utc-offset": _format_utc_offset,
    "integer": _parse_int_val,
    "float": _parse_float_val,
    "boolean": lambda v: v.strip().upper() == "TRUE",
    "recur": _format_recur_to_jcal,
}


def _convert_value_to_jcal(val_type: str, raw_val: str) -> JCalScalar:
    """Convert raw property value string to jCal typed value."""
    converter = CONVERTERS_TO_JCAL.get(val_type)
    if converter is not None:
        return converter(raw_val)
    return raw_val


def _convert_value_to_ics(val_type: str, val: JCalScalar) -> str:
    """Convert jCal typed value back to iCalendar string."""
    if val_type == "text":
        return _escape_text(str(val))
    if val_type in ("date-time", "date", "time"):
        return _parse_iso_datetime_to_ics(str(val))
    if val_type == "utc-offset":
        return _parse_utc_offset_to_ics(str(val))
    if val_type == "recur" and isinstance(val, (dict, str)):
        return _format_recur_to_ics(val)
    if val_type == "float" and isinstance(val, list):
        return ";".join(str(item) for item in val)
    if val_type == "boolean":
        return "TRUE" if val else "FALSE"
    return str(val)


def _unfold_lines(text: str) -> list[str]:
    """Unfold RFC 5545 lines (CRLF + whitespace continuation)."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    unfolded: list[str] = []
    for line in normalized.split("\n"):
        if not line:
            continue
        if line[0] in (" ", "\t") and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded


def _parse_params(
    param_str: str,
) -> tuple[dict[str, str | list[str]], str | None]:
    """Parse parameter string into lowercase dict and optional VALUE type override."""
    params: dict[str, str | list[str]] = {}
    val_type_override: str | None = None
    if not param_str:
        return params, val_type_override

    tokens = re.findall(r'([^;="]+)(?:=(?:"([^"]*)"|([^;]*)))?', param_str)
    for p_name, q_val, u_val in tokens:
        p_key = p_name.strip().lower()
        p_val = q_val if q_val else u_val.strip()
        if p_key == "value":
            val_type_override = p_val.lower()
            continue

        if "," in p_val and not q_val:
            params[p_key] = [item.strip() for item in p_val.split(",")]
        else:
            params[p_key] = p_val

    return params, val_type_override


def _process_property_entry(
    name: str,
    param_str: str,
    val_str: str,
) -> list[Any]:
    """Build a 4-element jCal property entry."""
    params, val_type_override = _parse_params(param_str)
    val_type = val_type_override or PROPERTY_TYPES.get(name, "text")

    if name in MULTI_VALUED_PROPERTIES and "," in val_str:
        raw_items = val_str.split(",")
        converted_items = [_convert_value_to_jcal(val_type, item) for item in raw_items]
        return [name, params, val_type, *converted_items]

    converted_val = _convert_value_to_jcal(val_type, val_str)
    return [name, params, val_type, converted_val]


def ics_to_jcal(ics_text: str) -> list[Any]:
    """Convert RFC 5545 iCalendar text into RFC 7265 jCal JSON data structure.

    Args:
        ics_text: Raw iCalendar (.ics) string.

    Returns:
        RFC 7265 jCal component 3-element list:
        ['vcalendar', [ [prop_name, {params}, val_type, *values], ... ], [ [subcomp, ...], ... ]]
    """
    lines = _unfold_lines(ics_text)
    stack: list[tuple[str, list[Any], list[Any]]] = []
    root: list[Any] | None = None

    for line in lines:
        if ":" not in line:
            continue
        header, val_str = line.split(":", 1)
        header_parts = header.split(";", 1)
        name = header_parts[0].strip().lower()
        param_str = header_parts[1] if len(header_parts) > 1 else ""

        if name == "begin":
            comp_name = val_str.strip().lower()
            stack.append((comp_name, [], []))
        elif name == "end":
            if stack:
                comp_name, props, subcomps = stack.pop()
                comp_array = [comp_name, props, subcomps]
                if stack:
                    stack[-1][2].append(comp_array)
                else:
                    root = comp_array
        elif stack:
            prop_entry = _process_property_entry(name, param_str, val_str)
            stack[-1][1].append(prop_entry)

    return root or ["vcalendar", [], []]


def _fold_line(line: str) -> str:
    """Fold an iCalendar line to 75 octets per RFC 5545 §3.1."""
    if len(line) <= 75:
        return line
    chunks: list[str] = [line[:75]]
    remaining = line[75:]
    while len(remaining) > 74:
        chunks.append(" " + remaining[:74])
        remaining = remaining[74:]
    if remaining:
        chunks.append(" " + remaining)
    return "\r\n".join(chunks)


def _format_property_line(prop: list[Any]) -> str:
    """Format single property to RFC 5545 string."""
    p_name = str(prop[0]).upper()
    p_params = prop[1] if isinstance(prop[1], dict) else {}
    p_type = str(prop[2]).lower()
    values = prop[3:]

    param_parts: list[str] = []
    default_type = PROPERTY_TYPES.get(p_name.lower(), "text")
    if p_type not in (default_type, "unknown"):
        param_parts.append(f"VALUE={p_type.upper()}")

    for param_k, param_v in p_params.items():
        k_upper = param_k.upper()
        if isinstance(param_v, list):
            v_str = ",".join(str(item) for item in param_v)
            param_parts.append(f"{k_upper}={v_str}")
        elif ":" in str(param_v) or ";" in str(param_v) or "," in str(param_v):
            param_parts.append(f'{k_upper}="{param_v}"')
        else:
            param_parts.append(f"{k_upper}={param_v}")

    param_prefix = (";" + ";".join(param_parts)) if param_parts else ""

    if len(values) > 1:
        val_strs = [_convert_value_to_ics(p_type, v) for v in values]
        val_out = ",".join(val_strs)
    elif len(values) == 1:
        val_out = _convert_value_to_ics(p_type, values[0])
    else:
        val_out = ""

    return f"{p_name}{param_prefix}:{val_out}"


def jcal_to_ics(jcal_comp: list[Any]) -> str:
    """Convert RFC 7265 jCal JSON data structure back into RFC 5545 iCalendar string.

    Args:
        jcal_comp: RFC 7265 3-element list [comp_name, properties, subcomponents].

    Returns:
        Formatted RFC 5545 iCalendar string with CRLF line endings.
    """
    if not isinstance(jcal_comp, (list, tuple)) or len(jcal_comp) < 3:
        return ""

    comp_name = str(jcal_comp[0]).upper()
    props = jcal_comp[1]
    subcomps = jcal_comp[2]

    lines = [f"BEGIN:{comp_name}"]

    for prop in props:
        if isinstance(prop, (list, tuple)) and len(prop) >= 4:
            line = _format_property_line(prop)
            lines.append(_fold_line(line))

    for sub in subcomps:
        sub_str = jcal_to_ics(sub)
        if sub_str:
            lines.append(sub_str)

    lines.append(f"END:{comp_name}")
    return "\r\n".join(lines)
