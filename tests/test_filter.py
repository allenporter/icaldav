"""Unit tests for iCalendar content filtering."""

from icaldav.filter import (
    CompFilter,
    TimeRange,
    extract_component_types,
    extract_time_range,
    matches_comp_filter,
    time_ranges_overlap,
)

# Sample iCalendar data
VEVENT_ICS = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:test-event-1@example.com\r\n"
    "DTSTART:20260715T100000Z\r\n"
    "DTEND:20260715T110000Z\r\n"
    "SUMMARY:Test Meeting\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR"
)

VTODO_ICS = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "BEGIN:VTODO\r\n"
    "UID:test-todo-1@example.com\r\n"
    "DTSTART:20260715T100000Z\r\n"
    "DUE:20260716T100000Z\r\n"
    "SUMMARY:Test Task\r\n"
    "END:VTODO\r\n"
    "END:VCALENDAR"
)


def test_extract_component_types_vevent() -> None:
    assert extract_component_types(VEVENT_ICS) == ["VEVENT"]


def test_extract_component_types_vtodo() -> None:
    assert extract_component_types(VTODO_ICS) == ["VTODO"]


def test_extract_time_range_vevent() -> None:
    assert extract_time_range(VEVENT_ICS) == ("20260715T100000Z", "20260715T110000Z")


def test_extract_time_range_date_only() -> None:
    date_ics = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        "DTSTART;VALUE=DATE:20260715\r\n"
        "DTEND;VALUE=DATE:20260716\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR"
    )
    assert extract_time_range(date_ics) == ("20260715", "20260716")


def test_time_ranges_overlap_inside() -> None:
    assert (
        time_ranges_overlap(
            "20260715T100000Z",
            "20260715T110000Z",
            "20260701T000000Z",
            "20260801T000000Z",
        )
        is True
    )


def test_time_ranges_overlap_outside() -> None:
    assert (
        time_ranges_overlap(
            "20260715T100000Z",
            "20260715T110000Z",
            "20260801T000000Z",
            "20260901T000000Z",
        )
        is False
    )


def test_time_ranges_overlap_partial() -> None:
    assert (
        time_ranges_overlap(
            "20260715T100000Z",
            "20260715T110000Z",
            "20260715T103000Z",
            "20260715T120000Z",
        )
        is True
    )


def test_time_ranges_overlap_open_start() -> None:
    assert (
        time_ranges_overlap(
            "20260715T100000Z", "20260715T110000Z", None, "20260801T000000Z"
        )
        is True
    )


def test_time_ranges_overlap_open_end() -> None:
    assert (
        time_ranges_overlap(
            "20260715T100000Z", "20260715T110000Z", "20260701T000000Z", None
        )
        is True
    )


def test_matches_comp_filter_vevent() -> None:
    filter_tree = CompFilter(name="VCALENDAR", comp_filters=[CompFilter(name="VEVENT")])
    assert matches_comp_filter(VEVENT_ICS, filter_tree) is True


def test_matches_comp_filter_vtodo_rejected() -> None:
    filter_tree = CompFilter(name="VCALENDAR", comp_filters=[CompFilter(name="VEVENT")])
    assert matches_comp_filter(VTODO_ICS, filter_tree) is False


def test_matches_comp_filter_with_time_range() -> None:
    filter_tree = CompFilter(
        name="VCALENDAR",
        comp_filters=[
            CompFilter(
                name="VEVENT",
                time_range=TimeRange(start="20260701T000000Z", end="20260801T000000Z"),
            )
        ],
    )
    assert matches_comp_filter(VEVENT_ICS, filter_tree) is True


def test_matches_comp_filter_with_time_range_miss() -> None:
    filter_tree = CompFilter(
        name="VCALENDAR",
        comp_filters=[
            CompFilter(
                name="VEVENT",
                time_range=TimeRange(start="20260801T000000Z", end="20260901T000000Z"),
            )
        ],
    )
    assert matches_comp_filter(VEVENT_ICS, filter_tree) is False
