"""Unit tests for iCalendar content filtering."""

from icaldav.filter import CompFilter, TimeRange, matches_comp_filter

VEVENT_ICS = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//Test//Test//EN\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:event-1@example.com\r\n"
    "DTSTART:20260715T100000Z\r\n"
    "DTEND:20260715T110000Z\r\n"
    "SUMMARY:Team Meeting\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR"
)

VTODO_ICS = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//Test//Test//EN\r\n"
    "BEGIN:VTODO\r\n"
    "UID:todo-1@example.com\r\n"
    "SUMMARY:Buy groceries\r\n"
    "END:VTODO\r\n"
    "END:VCALENDAR"
)


def test_matches_comp_filter_vevent() -> None:
    filter_tree = CompFilter(name="VCALENDAR", comp_filters=[CompFilter(name="VEVENT")])
    assert matches_comp_filter(VEVENT_ICS, filter_tree) is True
    assert matches_comp_filter(VTODO_ICS, filter_tree) is False


def test_matches_comp_filter_vtodo() -> None:
    filter_tree = CompFilter(name="VCALENDAR", comp_filters=[CompFilter(name="VTODO")])
    assert matches_comp_filter(VTODO_ICS, filter_tree) is True
    assert matches_comp_filter(VEVENT_ICS, filter_tree) is False


def test_matches_comp_filter_with_time_range() -> None:
    hit_filter = CompFilter(
        name="VCALENDAR",
        comp_filters=[
            CompFilter(
                name="VEVENT",
                time_range=TimeRange(
                    start="20260701T000000Z",
                    end="20260801T000000Z",
                ),
            )
        ],
    )
    miss_filter = CompFilter(
        name="VCALENDAR",
        comp_filters=[
            CompFilter(
                name="VEVENT",
                time_range=TimeRange(
                    start="20260801T000000Z",
                    end="20260901T000000Z",
                ),
            )
        ],
    )
    assert matches_comp_filter(VEVENT_ICS, hit_filter) is True
    assert matches_comp_filter(VEVENT_ICS, miss_filter) is False


def test_vtimezone_does_not_clobber_vevent_time_range() -> None:
    """VTIMEZONE placed after VEVENT must not clobber VEVENT's DTSTART."""
    ics_with_tz_after = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Test//Test//EN\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:event-tz@example.com\r\n"
        "DTSTART:20260715T100000Z\r\n"
        "DTEND:20260715T110000Z\r\n"
        "SUMMARY:Event Before Timezone\r\n"
        "END:VEVENT\r\n"
        "BEGIN:VTIMEZONE\r\n"
        "TZID:America/New_York\r\n"
        "BEGIN:STANDARD\r\n"
        "DTSTART:19701101T020000\r\n"
        "TZOFFSETFROM:-0400\r\n"
        "TZOFFSETTO:-0500\r\n"
        "END:STANDARD\r\n"
        "END:VTIMEZONE\r\n"
        "END:VCALENDAR"
    )
    july_filter = CompFilter(
        name="VCALENDAR",
        comp_filters=[
            CompFilter(
                name="VEVENT",
                time_range=TimeRange(
                    start="20260701T000000Z",
                    end="20260801T000000Z",
                ),
            )
        ],
    )
    assert matches_comp_filter(ics_with_tz_after, july_filter) is True


def test_folded_lines_and_duration() -> None:
    """RFC 5545 folded lines and DURATION properties are evaluated via ical."""
    folded_duration_ics = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Test//Test//EN\r\n"
        "BEGIN:VEV\r\n"
        " ENT\r\n"
        "UID:folded-1@example.com\r\n"
        "DTSTART:202607\r\n"
        " 15T100000Z\r\n"
        "DURATION:PT2H\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR"
    )
    overlap_second_hour = CompFilter(
        name="VCALENDAR",
        comp_filters=[
            CompFilter(
                name="VEVENT",
                time_range=TimeRange(
                    start="20260715T110000Z",
                    end="20260715T130000Z",
                ),
            )
        ],
    )
    assert matches_comp_filter(folded_duration_ics, overlap_second_hour) is True


def test_all_day_and_recurring_events() -> None:
    """All-day VALUE=DATE events and RRULE recurring events are evaluated via ical."""
    all_day_ics = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Test//Test//EN\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:allday@example.com\r\n"
        "DTSTART;VALUE=DATE:20260715\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR"
    )
    rrule_ics = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Test//Test//EN\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:rrule-1@example.com\r\n"
        "DTSTART:20260701T090000Z\r\n"
        "DTEND:20260701T100000Z\r\n"
        "RRULE:FREQ=DAILY;COUNT=5\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR"
    )
    july_15_filter = CompFilter(
        name="VCALENDAR",
        comp_filters=[
            CompFilter(
                name="VEVENT",
                time_range=TimeRange(
                    start="20260715T100000Z",
                    end="20260715T110000Z",
                ),
            )
        ],
    )
    july_3_filter = CompFilter(
        name="VCALENDAR",
        comp_filters=[
            CompFilter(
                name="VEVENT",
                time_range=TimeRange(
                    start="20260703T000000Z",
                    end="20260704T000000Z",
                ),
            )
        ],
    )
    assert matches_comp_filter(all_day_ics, july_15_filter) is True
    assert matches_comp_filter(rrule_ics, july_3_filter) is True
