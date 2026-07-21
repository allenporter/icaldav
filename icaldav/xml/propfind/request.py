"""WebDAV PROPFIND XML request building and parsing.

RFC Reference:
    - RFC 4918 Section 9.1: PROPFIND Method.
    - RFC 4918 Section 14.20: DAV:propfind Element.
"""

from collections.abc import Sequence
import logging
import xml.etree.ElementTree as ET

from icaldav.xml.namespaces import DAV, qname, strip_ns

_LOGGER = logging.getLogger(__name__)


def build_propfind_xml(props: Sequence[str] | None = None) -> bytes:
    """Build a <d:propfind> XML request body bytes.

    RFC Reference:
        - RFC 4918 Section 9.1: PROPFIND Method.
        - RFC 4918 Section 14.20: DAV:propfind Element.

    Args:
        props: Sequence of property names to request (e.g., ["resourcetype", "getetag", "displayname"]).
            If None or empty, generates an empty <d:propfind/> or <d:allprop/> request.

    Returns:
        Encoded UTF-8 XML byte string.
    """
    root = ET.Element(qname(DAV, "propfind"))

    if not props:
        ET.SubElement(root, qname(DAV, "allprop"))
    else:
        prop_elem = ET.SubElement(root, qname(DAV, "prop"))
        for prop_name in props:
            # Support both short names ("getetag") and namespace-qualified names
            if prop_name.startswith("{"):
                prop_elem.append(ET.Element(prop_name))
            else:
                ET.SubElement(prop_elem, qname(DAV, prop_name))

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def parse_propfind_request(xml_bytes: bytes) -> list[tuple[str, str]] | None:
    """Parse a <DAV:propfind> XML request body to extract requested property names.

    RFC Reference:
        - RFC 4918 Section 9.1: PROPFIND Method.
        - RFC 4918 Section 14.20: DAV:propfind Element.

    Args:
        xml_bytes: Raw XML request byte payload.

    Returns:
        A list of (namespace, local_tag) tuples if explicit properties were requested in <DAV:prop>,
        or None if <DAV:allprop/>, <DAV:propname/>, or no body was supplied.
    """
    if not xml_bytes or not xml_bytes.strip():
        return None

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        _LOGGER.debug("Failed to parse PROPFIND request XML", exc_info=True)
        return None

    if strip_ns(root.tag) != "propfind":
        return None

    for child in root:
        if strip_ns(child.tag) == "prop":
            props: list[tuple[str, str]] = []
            for prop in child:
                tag = prop.tag
                if tag.startswith("{") and "}" in tag:
                    ns_part, local_tag = tag[1:].split("}", 1)
                    props.append((ns_part, local_tag))
                else:
                    props.append((DAV, tag))
            return props

    return None
