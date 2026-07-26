# Server Roadmap

Feature gaps identified by comparing CalDavRouter against Radicale via live protocol testing.

## Must-Have: Real Client Compatibility

These are required for Apple Calendar, Thunderbird, and DAVx⁵ to discover and sync with our server.

- [x] **Honest DAV compliance header** — stop advertising `DAV: 2` (locking) and `access-control` that we don't implement; only advertise `1, calendar-access`
- [x] **`/.well-known/caldav` redirect** — 301 redirect to root (RFC 6764 §5); without this, clients can't auto-discover our server
- [x] **MKCALENDAR method** — create calendar collections (RFC 4791 §5.3.1); currently returns 405
- [x] **Principal discovery properties** — return `DAV:current-user-principal` and `CALDAV:calendar-home-set` in PROPFIND responses (RFC 5397 §3, RFC 4791 §6.2.1)
- [x] **REPORT method: calendar-query** — filter events by component type, date range, etc. (RFC 4791 §7.8); this is how real clients fetch events efficiently
- [x] **REPORT method: calendar-multiget** — batch-fetch multiple resources by href (RFC 4791 §7.9); used by clients after PROPFIND to bulk-download changed events
- [x] **404 propstat for unsupported properties** — when a client requests properties we don't have (e.g. `displayname` on a resource), return them grouped under a `404` propstat block instead of silently omitting them (RFC 4918 §9.1)

## Should-Have: Correctness & Polish

- [ ] **`displayname` property on collections** — return collection display name in PROPFIND
- [ ] **Collection-level ETag** — Radicale returns ETags on collections for quick "has anything changed?" checks
- [ ] **`CALDAV:supported-calendar-component-set`** — advertise supported component types (VEVENT, VTODO, VJOURNAL)
- [ ] **Server auth middleware** — optional Basic Auth for multi-user setups
- [ ] **Dynamic Multi-User Principal & Home-Set Resolution** — replace single-user default URLs (`/principals/user/`, `/`, `mailto:user@localhost`) with session-derived user paths once multi-user auth/store is integrated
- [ ] **`Content-Security-Policy` header** — `default-src 'self'; object-src 'none'`

## Nice-to-Have: Advanced Sync

- [ ] **sync-token on collections** — incremental change detection (RFC 6578)
- [ ] **REPORT sync-collection** — only return resources changed since last sync-token (RFC 6578 §3.2); huge performance win for large calendars
- [ ] **CTag** — Apple's proprietary collection change tag; widely supported
- [ ] **PROPPATCH method** — set/remove properties like displayname, calendar color (RFC 4918 §9.2)
- [ ] **MOVE method** — rename/move resources between collections (RFC 4918 §9.9)
