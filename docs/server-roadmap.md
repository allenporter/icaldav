# Server Roadmap & Spec Compliance Audit

Feature status, specification compliance matrix, and implementation maturity tracking for `CalDavRouter`.

---

## Specification Compliance & Maturity Matrix

| Specification / Domain | Scope & Key Features | Our Implementation | Spec Coverage % | Implementation Maturity |
|---|---|---|---|---|
| **CalDAV Core (RFC 4791)** | Resource GET/PUT/DELETE, `calendar-query` REPORT (component & time-range filters), `calendar-multiget` REPORT, component sets, max resource size. | GET/PUT/DELETE, `calendar-query`, `calendar-multiget`, component set props, `max-resource-size`. | **~85%** | **Production-Grade**: Full recursive `CompFilter` & `TimeRange` parser, `ETag`/`If-Match` checks. |
| **WebDAV Core (RFC 4918)** | `PROPFIND` (`allprop`, `prop`), `MKCOL`/`MKCALENDAR`, `DELETE`, `GET`, `PUT`, `OPTIONS`, `COPY`, `MOVE`, `LOCK`/`UNLOCK`. | `PROPFIND`, `MKCALENDAR`, `DELETE`, `GET`, `PUT`, `OPTIONS`. (Missing: `COPY`, `MOVE`, `LOCK`/`UNLOCK`). | **~60%** | **Production-Grade**: Multi-Status XML parsing/building, `404` propstat blocks. |
| **WebDAV Autodiscovery (RFC 6764)** | `.well-known/caldav` redirects, `calendar-home-set` resolution. | `.well-known/caldav` route handler, `calendar-home-set` properties. | **~90%** | **Production-Grade**: Well-known endpoint and home-set resolution work across iOS/macOS clients. |
| **ACL & Identity (RFC 3744 / RFC 5397)** | `current-user-principal`, `principal-URL`, `owner`, `current-user-privilege-set`, `principal-property-search`, `ACL` method. | Principal properties, autodiscovery, `principal-property-search` REPORT. (Missing: `ACL` method & granular ACE management). | **~50%** | **Medium**: Autodiscovery and `principal-property-search` filtering functional; static privilege sets returned. |
| **WebDAV Sync (RFC 6578)** | `sync-token` property, `sync-collection` REPORT, tombstone deletion tracking, `<DAV:limit>` pagination. | Basic `sync-token` & `sync-collection` REPORT returning current collection ETags. | **~40%** | **Basic / Prototype**: Lacks deleted item tombstones (404 status diffs) and `<DAV:limit>` multi-page token pagination. |
| **CalDAV Scheduling (RFC 6638)** | Outbox / Inbox collections, `free-busy-query` REPORT, iTIP invitations (`REQUEST`, `REPLY`, `CANCEL`). | Out of scope. | **0%** | Excluded |
| **CalDAV Sharing (RFC 8607)** | Shared calendar notifications, read/write delegation. | Out of scope. | **0%** | Excluded |

---

## Completed Features

These are required for Apple Calendar, Thunderbird, DAVx⁵, and test tools to discover and sync with our server.

- [x] **Honest DAV compliance header** — stop advertising `DAV: 2` (locking) and `access-control` that we don't implement; only advertise `1, calendar-access` (RFC 4791 §5.1)
- [x] **`/.well-known/caldav` redirect** — 301 redirect to root (RFC 6764 §5); without this, clients can't auto-discover our server
- [x] **MKCALENDAR method** — create calendar collections (RFC 4791 §5.3.1)
- [x] **Trailing slash route normalization** — accept both `/collection` and `/collection/` routes in `CalDavRouter`
- [x] **Principal discovery properties & `/principals/` routing** — return `DAV:current-user-principal`, `DAV:principal-URL`, `CALDAV:calendar-home-set`, and `CALDAV:calendar-user-address-set` in PROPFIND responses (RFC 5397 §3, RFC 4791 §6.2.1, RFC 3744 §4.2)
- [x] **PrincipalStore & PrincipalInfo scaffolding** — abstract principal metadata resolution (`PrincipalInfo`, `PrincipalStore`, `InMemoryPrincipalStore`) for router and XML response generation
- [x] **REPORT method: calendar-query** — filter events by component type, date range, etc. (RFC 4791 §7.8); this is how real clients fetch events efficiently
- [x] **REPORT method: calendar-multiget** — batch-fetch multiple resources by href (RFC 4791 §7.9); used by clients after PROPFIND to bulk-download changed events
- [x] **404 propstat for unsupported properties** — when a client requests properties we don't have (e.g. `displayname` on a resource), return them grouped under a `404` propstat block instead of silently omitting them (RFC 4918 §9.1)
- [x] **`displayname` property on collections** — return collection display name in PROPFIND (RFC 4918 §14.11)
- [x] **Apple CTag (`<CS:getctag>`)** — return Apple CalDAV CTag on calendar collections for fast change detection
- [x] **`DAV:owner` property** — return principal path owner href on calendar collections (RFC 3744 §5.1)
- [x] **`DAV:current-user-privilege-set` property** — return full read/write privilege set (RFC 3744 §5.3)
- [x] **`CALDAV:max-resource-size` property** — advertise 10MB maximum resource payload size (RFC 4791 §5.2.5)
- [x] **`CALDAV:supported-calendar-component-set` property** — advertise supported component types (VEVENT, VTODO, VJOURNAL) (RFC 4791 §5.2.3)
- [x] **`DAV:supported-report-set` property** — advertise supported report types (`calendar-query`, `calendar-multiget`, `principal-property-search`, `sync-collection`) (RFC 3253 §3.1.5, RFC 4791 §5.3.1)
- [x] **`DAV:principal-property-search` REPORT** — search principal directory by property criteria with `CalDavClient` support (RFC 3744 §9.4)
- [x] **`DAV:sync-token` property & `sync-collection` REPORT** — initial WebDAV Sync support for delta synchronization (RFC 6578 §3, §6.1)

---

## Known Gaps & Technical Debt (To Make "Non-Toy")

- [ ] **WebDAV Sync Pagination & Tombstones (RFC 6578 §3.7 / §3.2)** — `sync-collection` currently returns all active ETags in a single batch. Implement deleted item tombstone responses (404 status items in sync diffs) and multi-page token pagination via `<DAV:limit><DAV:nresults>`.
- [ ] **Persistent Multi-User PrincipalStore** — user database / directory backend for `PrincipalStore` returning dynamic user-scoped principal metadata.
- [ ] **PROPPATCH method** — set/remove properties like `displayname`, calendar color (RFC 4918 §9.2).
- [ ] **MOVE / COPY methods** — move/copy resources between collections (RFC 4918 §9.8, §9.9).
- [ ] **Collection-level ETag** — compute collection ETags for quick top-level change validation.
- [ ] **Server auth middleware** — optional Basic Auth / OAuth token validation for multi-user setups.
- [ ] **`Content-Security-Policy` header** — `default-src 'self'; object-src 'none'`.
