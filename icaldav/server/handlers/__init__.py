"""Server HTTP request handlers for WebDAV and CalDAV endpoints."""

from icaldav.server.handlers.collection import CollectionHandler
from icaldav.server.handlers.discovery import handle_options, handle_well_known
from icaldav.server.handlers.propfind import PropfindHandler
from icaldav.server.handlers.report import ReportHandler
from icaldav.server.handlers.resource import ResourceHandler

__all__ = [
    "CollectionHandler",
    "PropfindHandler",
    "ReportHandler",
    "ResourceHandler",
    "handle_options",
    "handle_well_known",
]
