import pytest

from icaldav.jcal.codec import (
    _parse_float_val,
    _parse_int_val,
    ics_to_jcal,
    jcal_to_ics,
)

SAMPLE_ICS = (
    "BEGIN:VCALENDAR\r\n"
    "PRODID:-//Example Corp.//EN\r\n"
    "VERSION:2.0\r\n"
    "CALSCALE:GREGORIAN\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:event-12345@example.com\r\n"
    "DTSTAMP:20260817T100000Z\r\n"
    "DTSTART:20260817T120000Z\r\n"
    "DTEND:20260817T130000Z\r\n"
    "SUMMARY:Project Architecture Sync\r\n"
    "DESCRIPTION:Discussion regarding RFC 7265 and pluggable wire formats.\r\n"
    "LOCATION:Conference Room A\r\n"
    "CATEGORIES:WORK,ARCHITECTURE\r\n"
    "STATUS:CONFIRMED\r\n"
    "SEQUENCE:0\r\n"
    "RRULE:FREQ=WEEKLY;COUNT=10;BYDAY=MO,WE\r\n"
    "ATTENDEE;CN=Alice Smith;ROLE=REQ-PARTICIPANT:mailto:alice@example.com\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR"
)


def test_ics_to_jcal_structure() -> None:
    """Verify ics_to_jcal produces compliant RFC 7265 JSON structure."""
    jcal = ics_to_jcal(SAMPLE_ICS)
    assert isinstance(jcal, list)
    assert len(jcal) == 3
    assert jcal[0] == "vcalendar"

    # Properties
    props = jcal[1]
    prodid_prop = next(p for p in props if p[0] == "prodid")
    assert prodid_prop == ["prodid", {}, "text", "-//Example Corp.//EN"]

    version_prop = next(p for p in props if p[0] == "version")
    assert version_prop == ["version", {}, "text", "2.0"]

    # Subcomponents
    subcomps = jcal[2]
    assert len(subcomps) == 1
    vevent = subcomps[0]
    assert vevent[0] == "vevent"

    vprops = vevent[1]
    uid_prop = next(p for p in vprops if p[0] == "uid")
    assert uid_prop == ["uid", {}, "text", "event-12345@example.com"]

    dtstart_prop = next(p for p in vprops if p[0] == "dtstart")
    assert dtstart_prop == ["dtstart", {}, "date-time", "2026-08-17T12:00:00Z"]

    dtend_prop = next(p for p in vprops if p[0] == "dtend")
    assert dtend_prop == ["dtend", {}, "date-time", "2026-08-17T13:00:00Z"]

    seq_prop = next(p for p in vprops if p[0] == "sequence")
    assert seq_prop == ["sequence", {}, "integer", 0]

    attendee_prop = next(p for p in vprops if p[0] == "attendee")
    assert attendee_prop[0] == "attendee"
    assert attendee_prop[1].get("cn") == "Alice Smith"
    assert attendee_prop[2] == "cal-address"
    assert attendee_prop[3] == "mailto:alice@example.com"

    rrule_prop = next(p for p in vprops if p[0] == "rrule")
    assert rrule_prop[0] == "rrule"
    assert rrule_prop[2] == "recur"
    assert rrule_prop[3]["freq"] == "WEEKLY"
    assert rrule_prop[3]["count"] == 10
    assert rrule_prop[3]["byday"] == ["MO", "WE"]


def test_jcal_to_ics_roundtrip() -> None:
    """Verify converting jCal to iCalendar preserves component data."""
    jcal = ics_to_jcal(SAMPLE_ICS)
    ics_out = jcal_to_ics(jcal)

    assert "BEGIN:VCALENDAR" in ics_out
    assert "BEGIN:VEVENT" in ics_out
    assert "SUMMARY:Project Architecture Sync" in ics_out
    assert "UID:event-12345@example.com" in ics_out
    assert "DTSTART:20260817T120000Z" in ics_out
    assert "DTEND:20260817T130000Z" in ics_out
    assert "END:VEVENT" in ics_out
    assert "END:VCALENDAR" in ics_out


def test_date_and_utc_offset_formatting() -> None:
    """Verify date-only and timezone offset conversions."""
    ics = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VTIMEZONE\r\n"
        "TZID:America/New_York\r\n"
        "BEGIN:STANDARD\r\n"
        "DTSTART:20261101T020000\r\n"
        "TZOFFSETFROM:-0400\r\n"
        "TZOFFSETTO:-0500\r\n"
        "END:STANDARD\r\n"
        "END:VTIMEZONE\r\n"
        "END:VCALENDAR"
    )
    jcal = ics_to_jcal(ics)
    subcomps = jcal[2]
    assert len(subcomps) == 1
    vtz = subcomps[0]
    assert vtz[0] == "vtimezone"
    stand = vtz[2][0]
    assert stand[0] == "standard"

    props = stand[1]
    from_prop = next(p for p in props if p[0] == "tzoffsetfrom")
    assert from_prop == ["tzoffsetfrom", {}, "utc-offset", "-04:00"]

    to_prop = next(p for p in props if p[0] == "tzoffsetto")
    assert to_prop == ["tzoffsetto", {}, "utc-offset", "-05:00"]

    # Back to ICS
    rebuilt_ics = jcal_to_ics(jcal)
    assert "TZOFFSETFROM:-0400" in rebuilt_ics
    assert "TZOFFSETTO:-0500" in rebuilt_ics


def test_text_unescaping_escaping() -> None:
    """Verify escaped commas, semicolons, and newlines in text fields."""
    ics = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:escape-test\r\n"
        "DESCRIPTION:Line 1\\nLine 2\\, with comma\\; and semi\\\\slash\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR"
    )
    jcal = ics_to_jcal(ics)
    vevent = jcal[2][0]
    desc_prop = next(p for p in vevent[1] if p[0] == "description")
    assert desc_prop[3] == "Line 1\nLine 2, with comma; and semi\\slash"

    rebuilt = jcal_to_ics(jcal)
    assert "Line 1\\nLine 2\\, with comma\\; and semi\\\\slash" in rebuilt


def test_typed_integer_and_float_properties() -> None:
    """Verify strongly typed integer and float conversions in jCal."""
    ics = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:typed-vals\r\n"
        "PRIORITY:1\r\n"
        "PERCENT-COMPLETE:75\r\n"
        "GEO:37.386013;-122.082932\r\n"
        "RRULE:FREQ=MONTHLY;BYMONTHDAY=1,15,31;BYSETPOS=-1\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR"
    )
    jcal = ics_to_jcal(ics)
    vprops = jcal[2][0][1]

    prio_prop = next(p for p in vprops if p[0] == "priority")
    assert prio_prop == ["priority", {}, "integer", 1]
    assert isinstance(prio_prop[3], int)

    pct_prop = next(p for p in vprops if p[0] == "percent-complete")
    assert pct_prop == ["percent-complete", {}, "integer", 75]
    assert isinstance(pct_prop[3], int)

    geo_prop = next(p for p in vprops if p[0] == "geo")
    assert geo_prop == ["geo", {}, "float", [37.386013, -122.082932]]
    assert isinstance(geo_prop[3][0], float)
    assert isinstance(geo_prop[3][1], float)

    rrule_prop = next(p for p in vprops if p[0] == "rrule")
    assert rrule_prop[3]["bymonthday"] == [1, 15, 31]
    assert rrule_prop[3]["bysetpos"] == -1

    # Roundtrip back to ICS
    rebuilt = jcal_to_ics(jcal)
    assert "PRIORITY:1" in rebuilt
    assert "PERCENT-COMPLETE:75" in rebuilt
    assert "GEO:37.386013;-122.082932" in rebuilt
    assert "BYMONTHDAY=1,15,31" in rebuilt
    assert "BYSETPOS=-1" in rebuilt


def test_parser_validation_errors() -> None:
    """Verify strict type parsers raise ValueError on invalid strings."""
    with pytest.raises(ValueError):
        _parse_int_val("not_an_int")

    with pytest.raises(ValueError):
        _parse_float_val("not_a_float")


def test_line_folding_and_unfolding() -> None:
    """Verify long lines are folded to 75 octets and unfolded properly."""
    long_desc = "A" * 150
    ics = (
        f"BEGIN:VCALENDAR\r\n"
        f"BEGIN:VEVENT\r\n"
        f"UID:long-line-test\r\n"
        f"DESCRIPTION:{long_desc}\r\n"
        f"END:VEVENT\r\n"
        f"END:VCALENDAR"
    )
    jcal = ics_to_jcal(ics)
    assert jcal[2][0][1][1][3] == long_desc

    rebuilt = jcal_to_ics(jcal)
    # Ensure lines are split and folded with CRLF + space
    assert "\r\n " in rebuilt

    # Ensure roundtrip preserves exact string
    restored_jcal = ics_to_jcal(rebuilt)
    assert restored_jcal[2][0][1][1][3] == long_desc


def test_multivalued_and_parameter_quoting() -> None:
    """Verify multi-valued properties and parameters containing special characters."""
    ics = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:multi-param-test\r\n"
        "CATEGORIES:DEV,TEST,RELEASE\r\n"
        'ATTENDEE;CN="Doe, Jane; Special":mailto:jane@example.com\r\n'
        "DTSTART;VALUE=DATE:20260817\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR"
    )
    jcal = ics_to_jcal(ics)
    vprops = jcal[2][0][1]

    cat_prop = next(p for p in vprops if p[0] == "categories")
    assert cat_prop[3:] == ["DEV", "TEST", "RELEASE"]

    att_prop = next(p for p in vprops if p[0] == "attendee")
    assert att_prop[1]["cn"] == "Doe, Jane; Special"

    dt_prop = next(p for p in vprops if p[0] == "dtstart")
    assert dt_prop[2] == "date"
    assert dt_prop[3] == "2026-08-17"

    rebuilt = jcal_to_ics(jcal)
    assert "CATEGORIES:DEV,TEST,RELEASE" in rebuilt
    assert "VALUE=DATE" in rebuilt
    assert "DTSTART;VALUE=DATE:20260817" in rebuilt


def test_malformed_jcal_handling() -> None:
    """Verify empty/malformed inputs to jcal_to_ics return empty string."""
    assert jcal_to_ics([]) == ""
    assert jcal_to_ics(["vcalendar"]) == ""
    assert jcal_to_ics(None) == ""  # type: ignore[arg-type]


def test_recurrence_advanced_and_boolean_properties() -> None:
    """Verify complex recurrence rules, booleans, and list parameters."""
    ics = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:advanced-rrule\r\n"
        "DTSTART:20260817T1430\r\n"
        "RRULE:FREQ=DAILY;INTERVAL=2;UNTIL=20261231T235959Z;BYHOUR=9,17;BYMINUTE=30\r\n"
        "ATTENDEE;MEMBER=group1,group2:mailto:user@example.com\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR"
    )
    jcal = ics_to_jcal(ics)
    vprops = jcal[2][0][1]

    rrule = next(p for p in vprops if p[0] == "rrule")[3]
    assert rrule["freq"] == "DAILY"
    assert rrule["interval"] == 2
    assert rrule["until"] == "2026-12-31T23:59:59Z"
    assert rrule["byhour"] == [9, 17]
    assert rrule["byminute"] == 30

    att = next(p for p in vprops if p[0] == "attendee")
    assert att[1]["member"] == ["group1", "group2"]

    rebuilt = jcal_to_ics(jcal)
    assert "FREQ=DAILY" in rebuilt
    assert "INTERVAL=2" in rebuilt
    assert "UNTIL=20261231T235959Z" in rebuilt
    assert "BYHOUR=9,17" in rebuilt
    assert "BYMINUTE=30" in rebuilt
