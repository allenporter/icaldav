"""WebDAV PROPPATCH XML response building and parsing.

RFC Reference:
    - RFC 4918 Section 9.2: PROPPATCH Method.
    - RFC 4918 Section 13: DAV:multistatus Response Schema.
"""

import http.client
import logging
import xml.etree.ElementTree as ET
from collections.abc import Sequence

from icaldav.store.types import PropertyTag
from icaldav.xml.namespaces import DAV, qname, strip_ns

_LOGGER = logging.getLogger(__name__)


def build_proppatch_response_xml(
    href: str,
    ok_props: Sequence[PropertyTag],
    failed_props: dict[PropertyTag, int] | None = None,
) -> bytes:
    """Build a <DAV:multistatus> 207 response XML for a PROPPATCH request.

    RFC 4918 §9.2.1 requires atomicity:
    If any property fails, all other properties MUST report 424 (Failed Dependency).

    Args:
        href: Target resource URI path.
        ok_props: Sequence of PropertyTag items that succeeded (or would have succeeded).
        failed_props: Optional mapping of PropertyTag to failed HTTP status codes (e.g. 403).

    Returns:
        UTF-8 encoded XML byte string.
    """
    root = ET.Element(qname(DAV, "multistatus"))
    response = ET.SubElement(root, qname(DAV, "response"))
    ET.SubElement(response, qname(DAV, "href")).text = href

    if failed_props:
        for tag, status_code in failed_props.items():
            status_phrase = http.client.responses.get(status_code, "Error")
            propstat = ET.SubElement(response, qname(DAV, "propstat"))
            prop = ET.SubElement(propstat, qname(DAV, "prop"))
            ET.SubElement(prop, qname(tag.namespace, tag.name))
            ET.SubElement(
                propstat, qname(DAV, "status")
            ).text = f"HTTP/1.1 {status_code} {status_phrase}"

        if ok_props:
            propstat = ET.SubElement(response, qname(DAV, "propstat"))
            prop = ET.SubElement(propstat, qname(DAV, "prop"))
            for tag in ok_props:
                ET.SubElement(prop, qname(tag.namespace, tag.name))
            ET.SubElement(
                propstat, qname(DAV, "status")
            ).text = "HTTP/1.1 424 Failed Dependency"
    elif ok_props:
        propstat = ET.SubElement(response, qname(DAV, "propstat"))
        prop = ET.SubElement(propstat, qname(DAV, "prop"))
        for tag in ok_props:
            ET.SubElement(prop, qname(tag.namespace, tag.name))
        ET.SubElement(propstat, qname(DAV, "status")).text = "HTTP/1.1 200 OK"

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _extract_propstat_status(propstat: ET.Element) -> int:
    status_elem = propstat.find(f"{{{DAV}}}status")
    if status_elem is None or not status_elem.text:
        return 200
    parts = status_elem.text.strip().split()
    return int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 200


def _process_propstat(
    propstat: ET.Element,
    result: dict[PropertyTag, int],
) -> None:
    if strip_ns(propstat.tag) != "propstat":
        return
    status_code = _extract_propstat_status(propstat)
    prop_elem = propstat.find(f"{{{DAV}}}prop")
    if prop_elem is None:
        return
    for child in prop_elem:
        tag_str = child.tag
        if tag_str.startswith("{") and "}" in tag_str:
            ns, name = tag_str[1:].split("}", 1)
        else:
            ns, name = DAV, tag_str
        result[PropertyTag(namespace=ns, name=name)] = status_code


def parse_proppatch_response(xml_bytes: bytes) -> dict[PropertyTag, int]:
    """Parse a <DAV:multistatus> PROPPATCH response into a PropertyTag -> status code mapping.

    Args:
        xml_bytes: Response XML bytes.

    Returns:
        Mapping of PropertyTag to integer HTTP status code (e.g. 200, 403, 424).
    """
    if not xml_bytes or not xml_bytes.strip():
        return {}

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        _LOGGER.debug("Failed to parse PROPPATCH response XML", exc_info=True)
        return {}

    if strip_ns(root.tag) != "multistatus":
        return {}

    result: dict[PropertyTag, int] = {}
    for resp in root:
        if strip_ns(resp.tag) == "response":
            for propstat in resp:
                _process_propstat(propstat, result)
    return result
