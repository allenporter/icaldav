"""jCal (RFC 7265) and JSON wire-format encoders and decoders for icaldav.

Enables pluggable JSON serialization for WebDAV/CalDAV IR dataclasses without
altering CoreWebDavEngine domain logic or storage layers.

RFC References:
    - RFC 7265: jCal: The JSON Format for iCalendar
    - RFC 4918: WebDAV Core
    - RFC 4791: CalDAV Core
    - RFC 6578: Collection Synchronization
"""

from icaldav.jcal import (
    codec,
    propfind,
    report,
    serializer,
)

__all__ = [
    "codec",
    "propfind",
    "report",
    "serializer",
]
