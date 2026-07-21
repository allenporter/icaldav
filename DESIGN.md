# Design Document: icaldav

This document codifies the core architectural decisions, design patterns, and scope boundaries for `icaldav`.

---

## 1. Architectural Philosophy

### Local-First Synchronization
CalDAV servers in the wild vary wildly in their adherence to RFC standards, particularly around server-side time-range queries (`calendar-query`) and recurrence expansion.

`icaldav` adopts a **local-first synchronization model**:
- The CalDAV server is treated strictly as a **remote document store** for raw `.ics` payloads.
- The client engine streams and caches raw `.ics` payloads into local storage.
- All timeline generation, date filtering, timezone conversion, and recurrence rule (`RRULE`, `EXDATE`, `RECURRENCE-ID`) expansions are executed **locally in-memory** using the [`ical`](https://github.com/allenporter/ical) engine.

### Division of Responsibilities

```
                                    +-----------------------+
                                    |     CalDAV Server     |
                                    +-----------------------+
                                                ^
                                                | HTTP / XML (WebDAV)
                                                v
+-----------------------------------------------------------------------------------+
| icaldav                                                                           |
|                                                                                   |
|  +------------------------+  RFC 6578 / ETag  +-------------------------------+  |
|  |  CalDavClient (httpx)  |  ---------------> | CalDavSyncManager             |  |
|  +------------------------+                   +-------------------------------+  |
|                                                               |                   |
|                                                               v                   |
|                                               +-------------------------------+  |
|                                               |  LocalStore (SQLite / Mem)    |  |
|                                               +-------------------------------+  |
+---------------------------------------------------------------|-------------------+
                                                                v Raw .ics
+-----------------------------------------------------------------------------------+
| ical                                                                              |
|                                                                                   |
|  +------------------------+                   +-------------------------------+  |
|  |  Calendar Parser       |  ---------------> | Timeline Engine               |  |
|  +------------------------+                   +-------------------------------+  |
+-----------------------------------------------------------------------------------+
```

- **`icaldav` Responsibilities:** HTTP transport, WebDAV XML query parsing/generation, authentication, collection discovery, incremental sync token management, and ASGI server routing.
- **`ical` Responsibilities:** RFC 5545 parsing, Pydantic model validation, recurrence calculations, and chronological event timeline slicing.

---

## 2. Sync Engine Architecture (`CalDavSyncManager`)

To support both high-performance servers and legacy/minimalist servers, `icaldav` implements a **Dual-Path Synchronization Strategy**.

```mermaid
graph TD
    A[Start Sync] --> B{Server advertises DAV:sync-token?}
    B -- Yes --> C[Path 1: WebDAV Sync RFC 6578]
    C --> D[Send sync-collection REPORT with token]
    D --> E[Process additions, modifications & deletions inline]

    B -- No --> F[Path 2: ETag Diff Fallback]
    F --> G[PROPFIND Depth: 1 for href + DAV:getetag]
    G --> H[Diff server {href: etag} against local store]
    H --> I[Fetch changed hrefs via calendar-multiget REPORT]

    E --> J[Update LocalStore & save new sync-token]
    I --> J
```

### Path 1: WebDAV Sync (RFC 6578)
1. Checks for the `DAV:sync-token` property on the target calendar collection.
2. Sends a `<sync-collection>` `REPORT` containing the last stored sync-token.
3. Requests `<c:calendar-data>` directly inline in the report response.
4. Updates local store and stores the new `DAV:sync-token`.
5. **Network Overhead:** 1 HTTP request for all incremental changes.

### Path 2: ETag Diff Fallback (Non-RFC 6578 Servers)
Used when connecting to servers that do not implement RFC 6578 (e.g. Radicale, Apple iCloud):
1. Sends a `PROPFIND` (`Depth: 1`) request fetching all resource `href`s and `DAV:getetag` values (metadata-only).
2. Diffs the remote `{href: etag}` dictionary against the local database:
   - **New `href`:** Schedule for fetch.
   - **Changed ETag:** Schedule for fetch.
   - **Missing `href`:** Delete locally.
3. Batch-fetches content for all new/changed `href`s using a single `<calendar-multiget>` `REPORT`.
4. **Network Overhead:** Exactly 2 HTTP requests regardless of calendar size.

---

## 3. Server Compatibility & Workaround Boundaries

By avoiding server-side `calendar-query` and date filtering, `icaldav` bypasses ~90% of legacy server bug workarounds (such as time-range filtering bugs, missing component type flags, and `is-not-defined` property search failures).

However, `icaldav` explicitly accounts for the following persistence quirks:

| Quirk / Issue | Known Servers | `icaldav` Handling |
| :--- | :--- | :--- |
| **Exception Splitting** | Stalwart | Master event and exception VEVENTs stored across separate files are unified by `UID` at store read time before passing to `ical`. |
| **Soft-Deleted UIDs** | Nextcloud Trashbin | Handled by assigning unique filename resource paths (`/calendar/{uid}.ics`) while keeping `UID` unique. |
| **Non-UTC Timezones** | Various | Inputs normalized to standard UTC / IANA timezones upon `PUT` operations. |
| **Missing Sync Tokens** | Radicale, iCloud | Automatically defaults to Path 2 (ETag Diffing) without throwing errors. |

---

## 4. Embeddable ASGI Server (`CalDavRouter`)

### Design Goal
Allow developers to mount a fully-functional CalDAV server endpoint inside existing Python web frameworks (FastAPI, Starlette, or Home Assistant's `aiohttp` webserver).

### Scope Boundaries for Server
To maintain a clean, maintainable codebase, the embedded server strictly limits its protocol scope:

#### Implemented Methods & Features
- **HTTP Methods:** `OPTIONS`, `PROPFIND`, `REPORT`, `PUT`, `DELETE`, `MKCALENDAR`.
- **Reports:** `calendar-multiget`, `calendar-query` (basic time-range slicing backed by `ical`), and `sync-collection` (RFC 6578).
- **Auth:** HTTP Basic Auth and Bearer Token.

#### Excluded Features (Explicitly Out of Scope)
- **CalDAV Scheduling (RFC 6638):** No server-side meeting invitations, reply processing, or free/busy scheduling between users.
- **WebDAV ACL (RFC 3744):** No complex multi-user permission trees; flat per-user calendar access.
- **CardDAV:** Contact synchronization is out of scope.

---

## 5. Storage Abstraction (`LocalStore`)

The sync manager relies on an abstract `LocalStore` interface:

```python
class LocalStore(Protocol):
    async def get_sync_token(self, collection_id: str) -> str | None: ...
    async def set_sync_token(self, collection_id: str, token: str) -> None: ...

    async def get_etags(self, collection_id: str) -> dict[str, str]: ...

    async def save_resource(self, collection_id: str, href: str, etag: str, ics_content: str) -> None: ...
    async def delete_resource(self, collection_id: str, href: str) -> None: ...

    async def get_calendar(self, collection_id: str) -> Calendar: ...
```

Built-in implementations will include:
- `MemoryStore`: Fast in-memory cache for transient applications and testing.
- `SQLiteStore`: Embedded persistent storage for desktop apps, CLI tools, and Home Assistant integrations.
