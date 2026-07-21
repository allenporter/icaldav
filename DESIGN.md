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

---

## 6. Development & Testing Principles

To ensure high reliability, fast local development iterations, and strict compliance, the project strictly adheres to six core testing and implementation principles:

### 1. In-Process Loopback Testing (ASGI Client + Server)
Unit tests for `CalDavClient` and `CalDavSyncManager` must use `httpx.ASGITransport` wired directly to `CalDavRouter`:
```python
# In-process loopback testing with zero network I/O
transport = httpx.ASGITransport(app=caldav_router_app)
async with CalDavClient(transport=transport, base_url="http://test") as client:
    ...
```
This enables executing hundreds of client-server synchronization tests in milliseconds without network overhead or Docker setup.

### 2. Multi-Server Docker Integration Matrix
CI integration testing runs against real-world CalDAV containers:
- **SabreDAV / Nextcloud:** Validates WebDAV Collection Synchronization (RFC 6578).
- **Radicale:** Validates ETag fallback diffing on a simple flat-file server.
- **Baïkal:** Validates multi-calendar discovery and standard WebDAV operations.

### 3. XML Snapshot Testing (`syrupy`)
WebDAV request payloads (`calendar-query`, `sync-collection`, `calendar-multiget`) and Multi-Status XML responses are tested against snapshot fixtures using `syrupy`. XML fixtures are seeded from standard test sources (such as `sabre-io/dav` XML test suites) to guarantee structural XML correctness.

### 4. Robust XML Namespace Isolation
All XML parsing must be namespace-agnostic, stripping prefix assumptions (`d:`, `C:`, `ns0:`, `DAV:`):
```python
# Match element tags by qualified name URI, not prefix strings
element.find("{DAV:}href")
```

### 5. Immutability of Raw `.ics` Bytes
The synchronization engine treats `.ics` calendar objects as raw, immutable text during transport. Re-encoding or formatting `.ics` payloads during sync is prohibited to prevent byte-checksum drift and false positive ETag mismatches.

### 6. Explicit RFC Spec Tracing
Every XML generator, parser module, and test case must link directly to its governing RFC section in its docstrings (e.g., `# RFC 6578 Section 3.2: The DAV:sync-collection REPORT`).

### 7. Industry Standard Compliance & Test Suite Sources
To ensure maximum compatibility and avoid inventing ad-hoc test cases, `icaldav` leverages five industry-standard test suites and test vector sources:

| Layer | Industry Source | Purpose / Scope |
| :--- | :--- | :--- |
| **Unit / Snapshots** | [`sabre-io/dav`](https://github.com/sabre-io/dav) XML Fixtures | Seeding XML request/response fixtures for unit and snapshot testing. |
| **In-Process Sync** | `httpx.ASGITransport` + `CalDavRouter` | Zero-I/O client-server synchronization testing. |
| **WebDAV Compliance** | [`notroj/litmus`](https://github.com/notroj/litmus) Test Runner | Automated RFC 4918 protocol compliance validation for `CalDavRouter`. |
| **CalDAV Compliance** | [`CalConnect/caldavtester`](https://github.com/CalConnect/caldavtester) | Automated RFC 4791 & RFC 6578 scenario validation. |
| **Server Integration** | [`python-caldav`](https://github.com/python-caldav/caldav) Test Matrix + Docker | Edge-case validation against Nextcloud, Stalwart, Radicale, and Baïkal. |

---

## 7. RFC Support Roadmap & Scope

The WebDAV/CalDAV ecosystem spans dozens of individual IETF RFCs because every minor extension historically received its own document number. To avoid scope creep, `icaldav` explicitly categorizes RFCs into three support tiers:

### Tier 1: Core Protocol Standards (Mandatory)
These core standards form the foundation of `icaldav`'s client transport, sync engine, and embeddable server:
- **[RFC 4791](https://datatracker.ietf.org/doc/html/rfc4791):** CalDAV Core — Calendar extensions to WebDAV (properties, `calendar-query`, `calendar-multiget`, `MKCALENDAR`).
- **[RFC 4918](https://datatracker.ietf.org/doc/html/rfc4918):** WebDAV Core — `PROPFIND`, `PROPPATCH`, `MKCOL`, Multi-Status XML responses, HTTP status code extensions.
- **[RFC 6578](https://datatracker.ietf.org/doc/html/rfc6578):** WebDAV Collection Synchronization — `DAV:sync-token` property and `<sync-collection>` `REPORT` for delta synchronization.
- **[RFC 5545](https://datatracker.ietf.org/doc/html/rfc5545):** iCalendar Core Data Format — Parsing, encoding, validation, and recurrence expansion (delegated to [`ical`](https://github.com/allenporter/ical)).
- **[RFC 6868](https://datatracker.ietf.org/doc/html/rfc6868):** iCalendar Parameter Value Encoding — Character escaping in property parameters (delegated to `ical`).

### Tier 2: Convenience & Extended Standards (Supported)
Optional or auxiliary standards supported for enhanced discovery and compliance:
- **[RFC 5397](https://datatracker.ietf.org/doc/html/rfc5397):** WebDAV Current Principal Extension — `DAV:current-user-principal` property for automatic user discovery.
- **[RFC 5689](https://datatracker.ietf.org/doc/html/rfc5689):** Extended `MKCOL` — Creating calendar collections via extended `MKCOL` requests.
- **[RFC 7986](https://datatracker.ietf.org/doc/html/rfc7986):** iCalendar Component Extensions — Support for newer iCalendar properties like `COLOR`, `IMAGE`, `CONFERENCE` (delegated to `ical`).
- **[RFC 8536](https://datatracker.ietf.org/doc/html/rfc8536):** Timezone Information Format (TZif) — (delegated to `ical`).

### Tier 3: Explicitly Excluded Standards (Out of Scope)
These RFCs add massive complexity without benefitting local-first calendar synchronization or lightweight server routing:
- **[RFC 6638](https://datatracker.ietf.org/doc/html/rfc6638):** CalDAV Scheduling Extensions — Server-side meeting invitations, outbox/inbox processing, organizer/attendee reply handling, and free-busy lookups between users.
- **[RFC 3744](https://datatracker.ietf.org/doc/html/rfc3744):** WebDAV Access Control List (ACL) — Multi-user hierarchical permission inheritance trees.
- **[RFC 6352](https://datatracker.ietf.org/doc/html/rfc6352) / [RFC 4792](https://datatracker.ietf.org/doc/html/rfc4792):** CardDAV — VCard and contact synchronization.
- **[RFC 7211](https://datatracker.ietf.org/doc/html/rfc7211):** CalDAV Managed Attachments — Server-side binary attachment management.
