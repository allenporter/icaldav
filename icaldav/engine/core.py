"""Core WebDAV logical evaluation engine for icaldav.

Decouples HTTP route handler routing and XML parsing/serialization from store
interactions and property evaluation.

RFC References:
    - RFC 4918: WebDAV Core
    - RFC 4791: CalDAV Core
    - RFC 6578: Collection Synchronization
    - RFC 3744: WebDAV Access Control Protocol
"""

from icaldav.engine.models import (
    CalendarMultigetQuery,
    CalendarQuery,
    PrincipalSearchQuery,
    PropertyTag,
    PropfindQuery,
    PropstatBlock,
    ReportMultiStatus,
    ReportResource,
    SyncCollectionQuery,
    WebDavMultiStatus,
    WebDavResourceStatus,
)
from icaldav.filter import matches_comp_filter
from icaldav.store.principal import PrincipalStore
from icaldav.store.types import (
    CollectionPath,
    LocalStore,
    ResourceKind,
    ResourcePath,
    ResourceTarget,
)
from icaldav.xml.namespaces import (
    CALDAV,
    CALSERVER,
    DAV,
    CalDavProp,
    CalServerProp,
    DavProp,
)

# --- Individual Property Resolvers to Enforce McCabe C901 (Complexity <= 8) ---


def _resolve_resourcetype(ctx: ResourceTarget) -> list[str]:
    if ctx.kind == ResourceKind.PRINCIPAL:
        return ["collection", "principal"]
    elif ctx.kind == ResourceKind.ROOT:
        return ["collection"]
    elif ctx.kind == ResourceKind.CALENDAR:
        return ["collection", "calendar"]
    return []


def _resolve_getetag(ctx: ResourceTarget) -> str | None:
    return ctx.etag


def _resolve_current_user_principal(ctx: ResourceTarget) -> str | None:
    return ctx.principal.principal_path if ctx.principal else None


def _resolve_principal_url(ctx: ResourceTarget) -> str | None:
    return ctx.principal.principal_path if ctx.principal else None


def _resolve_owner(ctx: ResourceTarget) -> str | None:
    return ctx.principal.principal_path if ctx.principal else None


def _resolve_current_user_privilege_set(ctx: ResourceTarget) -> list[str]:
    return ["read", "write"]


def _resolve_supported_report_set(ctx: ResourceTarget) -> list[PropertyTag] | None:
    if ctx.kind in (ResourceKind.ROOT, ResourceKind.CALENDAR, ResourceKind.PRINCIPAL):
        return [
            PropertyTag(DAV, "expand-property"),
            PropertyTag(DAV, "principal-property-search"),
            PropertyTag(DAV, "sync-collection"),
        ]
    return None


def _resolve_sync_token(ctx: ResourceTarget) -> str | None:
    return ctx.sync_token


def _resolve_displayname(ctx: ResourceTarget) -> str | None:
    if ctx.kind == ResourceKind.ROOT:
        return "root"
    elif ctx.kind == ResourceKind.PRINCIPAL and ctx.principal:
        return ctx.principal.display_name
    elif ctx.kind == ResourceKind.CALENDAR and ctx.displayname:
        return ctx.displayname
    return None


def _resolve_calendar_home_set(ctx: ResourceTarget) -> str | None:
    return ctx.principal.calendar_home_path if ctx.principal else None


def _resolve_calendar_user_address_set(ctx: ResourceTarget) -> str | None:
    return ctx.principal.email if ctx.principal else None


def _resolve_supported_calendar_component_set(ctx: ResourceTarget) -> list[str] | None:
    if ctx.kind == ResourceKind.CALENDAR:
        return ["VEVENT", "VTODO"]
    return None


def _resolve_max_resource_size(ctx: ResourceTarget) -> str | None:
    if ctx.kind == ResourceKind.CALENDAR:
        return "10485760"
    return None


def _resolve_getctag(ctx: ResourceTarget) -> str | None:
    if ctx.kind == ResourceKind.CALENDAR:
        token = ctx.sync_token or "default"
        return f'"ctag-{token}"'
    return None


# Registry maps qualified property tags to target resolver methods
RESOLVER_REGISTRY = {
    (DAV, DavProp.RESOURCETYPE): _resolve_resourcetype,
    (DAV, DavProp.GETETAG): _resolve_getetag,
    (DAV, DavProp.CURRENT_USER_PRINCIPAL): _resolve_current_user_principal,
    (DAV, DavProp.PRINCIPAL_URL): _resolve_principal_url,
    (DAV, DavProp.OWNER): _resolve_owner,
    (DAV, DavProp.CURRENT_USER_PRIVILEGE_SET): _resolve_current_user_privilege_set,
    (DAV, DavProp.SUPPORTED_REPORT_SET): _resolve_supported_report_set,
    (DAV, DavProp.SYNC_TOKEN): _resolve_sync_token,
    (DAV, DavProp.DISPLAYNAME): _resolve_displayname,
    (CALDAV, CalDavProp.CALENDAR_HOME_SET): _resolve_calendar_home_set,
    (CALDAV, CalDavProp.CALENDAR_USER_ADDRESS_SET): _resolve_calendar_user_address_set,
    (
        CALDAV,
        CalDavProp.SUPPORTED_CALENDAR_COMPONENT_SET,
    ): _resolve_supported_calendar_component_set,
    (CALDAV, CalDavProp.MAX_RESOURCE_SIZE): _resolve_max_resource_size,
    (CALSERVER, CalServerProp.GETCTAG): _resolve_getctag,
}


class CoreWebDavEngine:
    """Logical execution core evaluating WebDAV and CalDAV query specifications."""

    def _evaluate_target(
        self,
        ctx: ResourceTarget,
        requested_props: list[PropertyTag] | None,
    ) -> WebDavResourceStatus:
        """Evaluate properties of a specific Target context, returning structured status block."""
        # If no properties were explicitly requested, default to all registry keys
        props_to_resolve = (
            requested_props
            if requested_props is not None
            else [PropertyTag(ns, name) for ns, name in RESOLVER_REGISTRY]
        )

        ok_props = {}
        err_props = {}

        for tag in props_to_resolve:
            resolver = RESOLVER_REGISTRY.get((tag.namespace, tag.name))
            if resolver is not None:
                val = resolver(ctx)
                if val is not None:
                    ok_props[tag] = val
                    continue
            err_props[tag] = ""

        blocks = []
        if ok_props:
            blocks.append(PropstatBlock(status_code=200, properties=ok_props))
        if err_props:
            blocks.append(PropstatBlock(status_code=404, properties=err_props))

        return WebDavResourceStatus(href=ctx.href, propstats=blocks)

    async def evaluate_propfind(
        self,
        store: LocalStore,
        principal_store: PrincipalStore,
        query: PropfindQuery,
    ) -> WebDavMultiStatus:
        """Perform a logical WebDAV PROPFIND query against storage layer.

        Args:
            store: LocalStore database instance.
            principal_store: PrincipalStore database instance.
            query: PropfindQuery IR representation of the request.

        Returns:
            WebDavMultiStatus containing status information for all resources.
        """
        responses: list[WebDavResourceStatus] = []

        # Determine target kind and properties
        href = query.href
        principal = await principal_store.get_principal(query.user_id)

        kind = ResourceKind.RESOURCE
        etag: str | None = None
        sync_token: str | None = None
        displayname: str | None = None

        if href.startswith("/principals/"):
            kind = ResourceKind.PRINCIPAL
        elif href == "/":
            kind = ResourceKind.ROOT
        else:
            coll_path = CollectionPath.parse(href)
            segments = [s for s in href.strip("/").split("/") if s]
            if len(segments) <= 1:
                kind = ResourceKind.CALENDAR
                sync_token = await store.get_sync_token(coll_path)
                displayname = coll_path.path.strip("/")
            else:
                res_path = ResourcePath.parse(href)
                res = await store.get_resource(res_path)
                if not res:
                    raise FileNotFoundError(f"Resource not found: {href}")
                kind = ResourceKind.RESOURCE
                etag = res.etag

        # 1. Evaluate target itself
        ctx = ResourceTarget(
            href=href,
            kind=kind,
            principal=principal,
            etag=etag,
            sync_token=sync_token,
            displayname=displayname,
        )
        responses.append(self._evaluate_target(ctx, query.requested_props))

        # 2. Evaluate children if Depth requires it
        if query.depth > 0 and kind == ResourceKind.CALENDAR:
            coll_path = CollectionPath.parse(href)
            resources = await store.get_resources(coll_path)
            for res in resources:
                child_ctx = ResourceTarget(
                    href=res.href,
                    kind=ResourceKind.RESOURCE,
                    principal=principal,
                    etag=res.etag,
                )
                responses.append(
                    self._evaluate_target(child_ctx, query.requested_props)
                )

        return WebDavMultiStatus(responses=responses)

    async def evaluate_sync_collection(
        self,
        store: LocalStore,
        collection: CollectionPath,
        query: SyncCollectionQuery,
    ) -> ReportMultiStatus:
        """Evaluate collection sync query mapping active resources and tombstones.

        Args:
            store: LocalStore database instance.
            collection: CollectionPath target identifier.
            query: SyncCollectionQuery IR representation of the request.

        Returns:
            ReportMultiStatus containing updated/deleted resource statuses and sync token.
        """
        changes = await store.get_changes_since(
            collection=collection,
            sync_token=query.sync_token,
            limit=query.limit,
        )
        matched = [
            ReportResource(href=res.href, etag=res.etag, ics_data=res.ics_data)
            for res in changes.changed
        ]
        return ReportMultiStatus(
            responses=matched,
            deleted_hrefs=changes.deleted_hrefs,
            sync_token=changes.sync_token,
        )

    async def evaluate_calendar_query(
        self,
        store: LocalStore,
        collection: CollectionPath,
        query: CalendarQuery,
    ) -> ReportMultiStatus:
        """Evaluate a calendar-query component filter tree against collection resources.

        Args:
            store: LocalStore database instance.
            collection: CollectionPath target identifier.
            query: CalendarQuery IR representation of the request.

        Returns:
            ReportMultiStatus containing matching resources.
        """
        all_resources = await store.get_resources(collection)
        include_data = any(
            p.name == "calendar-data" and p.namespace == CALDAV for p in query.props
        )

        matched = []
        for resource in all_resources:
            if matches_comp_filter(resource.ics_data, query.comp_filter):
                matched.append(
                    ReportResource(
                        href=resource.href,
                        etag=resource.etag,
                        ics_data=resource.ics_data if include_data else None,
                    )
                )

        return ReportMultiStatus(responses=matched)

    async def evaluate_calendar_multiget(
        self,
        store: LocalStore,
        query: CalendarMultigetQuery,
    ) -> ReportMultiStatus:
        """Resolve specific resource paths for calendar-multiget.

        Args:
            store: LocalStore database instance.
            query: CalendarMultigetQuery IR representation of the request.

        Returns:
            ReportMultiStatus containing resolved resources.
        """
        include_data = any(
            p.name == "calendar-data" and p.namespace == CALDAV for p in query.props
        )

        found = []
        missing = []
        for href in query.hrefs:
            resource = await store.get_resource(ResourcePath.parse(href))
            if resource:
                found.append(
                    ReportResource(
                        href=resource.href,
                        etag=resource.etag,
                        ics_data=resource.ics_data if include_data else None,
                    )
                )
            else:
                missing.append(href)

        return ReportMultiStatus(responses=found, missing_hrefs=missing)

    async def evaluate_principal_search(
        self,
        principal_store: PrincipalStore,
        query: PrincipalSearchQuery,
    ) -> WebDavMultiStatus:
        """Search principals directory matching criteria, mapping to WebDavMultiStatus.

        Args:
            principal_store: PrincipalStore database instance.
            query: PrincipalSearchQuery IR representation of the request.

        Returns:
            WebDavMultiStatus containing status information for matching principals.
        """
        principals = []
        match_terms = [c.match for c in query.criteria if c.match]

        if match_terms:
            for term in match_terms:
                found = await principal_store.search_principals(term)
                for p in found:
                    if p not in principals:
                        principals.append(p)
        else:
            principal = await principal_store.get_principal(query.user_id)
            if principal:
                principals.append(principal)

        responses = []
        for p in principals:
            ctx = ResourceTarget(
                href=p.principal_path,
                kind=ResourceKind.PRINCIPAL,
                principal=p,
            )
            responses.append(self._evaluate_target(ctx, query.props))

        return WebDavMultiStatus(responses=responses)
