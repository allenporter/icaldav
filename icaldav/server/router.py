"""Embeddable WebDAV / CalDAV web application router based on aiohttp.web.

RFC References:
  - RFC 4918: WebDAV Specification.
  - RFC 4791: CalDAV Specification.
"""

from aiohttp import web

from icaldav.server.handlers.collection import CollectionHandler
from icaldav.server.handlers.discovery import handle_options, handle_well_known
from icaldav.server.handlers.propfind import PropfindHandler
from icaldav.server.handlers.report import ReportHandler
from icaldav.server.handlers.resource import ResourceHandler
from icaldav.store.principal import PrincipalStore
from icaldav.store.types import LocalStore


class CalDavRouter:
    """Embeddable CalDAV server router producing an aiohttp.web.Application.

    RFC Reference:
        - RFC 4918: WebDAV Specification.
        - RFC 4791: CalDAV Specification.
    """

    def __init__(
        self,
        store: LocalStore,
        principal_store: PrincipalStore | None = None,
    ) -> None:
        """Initialize router with storage and principal resolution implementations.

        Args:
            store: An implementation of the LocalStore protocol.
            principal_store: Optional implementation of the PrincipalStore protocol.
        """
        self.store = store
        self.principal_store = principal_store
        self.propfind_handler = PropfindHandler(store, principal_store=principal_store)
        self.report_handler = ReportHandler(store)
        self.resource_handler = ResourceHandler(store)
        self.collection_handler = CollectionHandler(store)

    def create_app(self) -> web.Application:
        """Create and configure an aiohttp.web.Application with WebDAV routes.

        Returns:
            Configured aiohttp.web.Application ready to serve requests or be tested.
        """
        app = web.Application(client_max_size=2 * 1024 * 1024)  # 2MB limit

        # Discovery & Autodiscovery (RFC 6764 §5, RFC 5397 §3)
        app.router.add_route("GET", "/.well-known/caldav", handle_well_known)
        app.router.add_route("OPTIONS", "/{tail:.*}", handle_options)
        app.router.add_route("PROPFIND", "/", self.propfind_handler.handle_root)
        app.router.add_route(
            "PROPFIND", "/principals/{tail:.*}", self.propfind_handler.handle_root
        )

        # Collections
        for path in ("/{collection_id}", "/{collection_id}/"):
            app.router.add_route(
                "MKCALENDAR", path, self.collection_handler.handle_mkcalendar
            )
            app.router.add_route(
                "PROPFIND", path, self.propfind_handler.handle_collection
            )
            app.router.add_route("REPORT", path, self.report_handler.handle_report)

        # Resources
        app.router.add_route(
            "PROPFIND",
            "/{collection_id}/{resource_id}",
            self.propfind_handler.handle_resource,
        )
        app.router.add_route(
            "GET", "/{collection_id}/{resource_id}", self.resource_handler.handle_get
        )
        app.router.add_route(
            "PUT", "/{collection_id}/{resource_id}", self.resource_handler.handle_put
        )
        app.router.add_route(
            "DELETE",
            "/{collection_id}/{resource_id}",
            self.resource_handler.handle_delete,
        )

        return app


def create_app(
    store: LocalStore,
    principal_store: PrincipalStore | None = None,
) -> web.Application:
    """Helper function to instantiate a CalDavRouter app for a given LocalStore."""
    return CalDavRouter(store, principal_store=principal_store).create_app()
