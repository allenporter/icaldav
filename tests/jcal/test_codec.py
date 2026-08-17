"""Unit tests for jCal (RFC 7265) <-> iCalendar (RFC 5545) codec."""

from icaldav.jcal.codec import ics_to_jcal, jcal_to_ics

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
