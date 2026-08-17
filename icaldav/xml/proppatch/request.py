"""WebDAV PROPPATCH XML request building and parsing.

RFC Reference:
    - RFC 4918 Section 9.2: PROPPATCH Method.
    - RFC 4918 Section 14.20: DAV:propertyupdate Element.
"""

import logging
import xml.etree.ElementTree as ET
from collections.abc import Sequence

from icaldav.store.types import PropertyTag
from icaldav.xml.namespaces import DAV, qname, strip_ns

_LOGGER = logging.getLogger(__name__)


def build_proppatch_xml(
    set_props: dict[PropertyTag, str] | None = None,
    remove_props: Sequence[PropertyTag] | None = None,
) -> bytes:
    """Build a <DAV:propertyupdate> XML request body.

    Args:
        set_props: Mapping of PropertyTag to string values to set.
        remove_props: Sequence of PropertyTag items to remove.

    Returns:
        UTF-8 encoded XML byte string.
    """
    root = ET.Element(qname(DAV, "propertyupdate"))

    if set_props:
        set_elem = ET.SubElement(root, qname(DAV, "set"))
        prop_elem = ET.SubElement(set_elem, qname(DAV, "prop"))
        for tag, val in set_props.items():
            p_child = ET.SubElement(prop_elem, qname(tag.namespace, tag.name))
            p_child.text = val

    if remove_props:
        remove_elem = ET.SubElement(root, qname(DAV, "remove"))
        prop_elem = ET.SubElement(remove_elem, qname(DAV, "prop"))
        for tag in remove_props:
            ET.SubElement(prop_elem, qname(tag.namespace, tag.name))

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _parse_tag(tag_str: str) -> PropertyTag:
    if tag_str.startswith("{") and "}" in tag_str:
        ns, name = tag_str[1:].split("}", 1)
    else:
        ns, name = DAV, tag_str
    return PropertyTag(namespace=ns, name=name)


def _extract_property_value(elem: ET.Element) -> str:
    if len(elem) > 0:
        return "".join(ET.tostring(child, encoding="unicode") for child in elem)
    return elem.text or ""


def _process_action_element(
    action: ET.Element,
    set_props: dict[PropertyTag, str],
    remove_props: list[PropertyTag],
) -> None:
    action_name = strip_ns(action.tag)
    if action_name not in ("set", "remove"):
        return

    for prop_wrapper in action:
        if strip_ns(prop_wrapper.tag) != "prop":
            continue
        for prop_elem in prop_wrapper:
            tag = _parse_tag(prop_elem.tag)
            if action_name == "set":
                set_props[tag] = _extract_property_value(prop_elem)
            elif action_name == "remove":
                remove_props.append(tag)


def parse_proppatch_request(
    xml_bytes: bytes,
) -> tuple[dict[PropertyTag, str], list[PropertyTag]]:
    """Parse a <DAV:propertyupdate> XML request body.

    Args:
        xml_bytes: Raw XML byte string from HTTP request.

    Returns:
        Tuple of (set_properties dict, remove_properties list).

    Raises:
        ValueError: If XML is invalid or root is not <propertyupdate>.
    """
    if not xml_bytes or not xml_bytes.strip():
        return {}, []

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as err:
        raise ValueError(f"Invalid XML payload: {err}") from err

    if strip_ns(root.tag) != "propertyupdate":
        raise ValueError(f"Expected root tag 'propertyupdate', got '{root.tag}'")

    set_props: dict[PropertyTag, str] = {}
    remove_props: list[PropertyTag] = []
    for action in root:
        _process_action_element(action, set_props, remove_props)

    return set_props, remove_props
