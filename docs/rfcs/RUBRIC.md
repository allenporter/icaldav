# CalDAV / WebDAV Production-Grade Maturity Rubric

This document defines the formal, objective criteria required for any specification requirement in `icaldav` to be classified as **Production-Grade** vs. **Prototype ("Toy")**.

---

## 1. Groundtruth Maturity Levels

Every requirement in `docs/rfcs/status/*.yaml` must be assigned exactly one of the following maturity levels:

| Maturity Level | Definition | Criteria Required |
|---|---|---|
| **`production_grade`** | Fully compliant, robust, persistent, and thoroughly tested implementation ready for production deployment. | **Must satisfy ALL 6 Rubric Criteria below.** |
| **`prototype` ("Toy")** | Functional for basic happy-path unit tests, but lacks persistence, edge-case error handling, or full spec features. | **Fails 1 or more Rubric Criteria below.** |
| **`not_implemented`** | Requirement is not implemented or explicitly out of scope. | **Not built.** |

---

## 2. The 6 Production-Grade Rubric Criteria

To be classified as **`production_grade`**, an implementation MUST satisfy ALL 6 of the following criteria:

### Criterion 1: Spec & XML Schema Compliance
* Implements all **MUST**, **MUST NOT**, **REQUIRED**, and **SHOULD** normative clauses in the governing RFC section.
* Generates and parses valid XML payloads using qualified namespace URIs (`DAV:`, `urn:ietf:params:xml:ns:caldav`), stripping arbitrary prefix assumptions (`d:`, `C:`, `ns0:`).
* Emits correct HTTP status codes (200, 207 Multi-Status, 400, 404, 412 Precondition Failed, 500).

### Criterion 2: Comprehensive Automated Test Coverage
* Verified by unit tests in `tests/` covering happy paths, boundary conditions, malformed XML inputs, and missing properties.
* Verified via zero-I/O in-process loopback testing using `CalDavClient` connected directly to `CalDavRouter` via `aiohttp.test_utils`.

### Criterion 3: Persistent Storage & State Isolation
* Supports persistent storage abstractions (`SQLiteStore`, database backends) rather than relying solely on transient in-memory dictionaries (`MemoryStore`).
* Maintains resource versioning and state isolation (`ETag` generation, change state tracking).

### Criterion 4: Concurrency & Precondition Safety
* Enforces HTTP conditional headers (`If-Match`, `If-None-Match`) to prevent mid-air collision overwrites during concurrent updates or deletions.
* Handles atomic collection state updates (e.g. updating collection ETags or sync-tokens upon resource modification).

### Criterion 5: Real-World Client Interoperability
* Interoperable with standard CalDAV clients (Apple Calendar, Thunderbird Lightning, DAVx⁵) and server test runners (`litmus`, `caldavtester`).
* Does not rely on proprietary or non-standard client/server assumptions.

### Criterion 6: Client & Server Dual-Layer Parity
* For features consumed by CalDAV clients, both the high-level `CalDavClient` method/parser AND the `CalDavRouter` server endpoint are fully implemented and documented with RFC references and docstring use cases.

---

## 3. Re-Audit Procedure

Whenever a requirement is proposed to be upgraded from `prototype` to `production_grade`:
1. Run `./script/test` and `./script/lint` to verify unit test and linter pass.
2. Verify against the 6 Rubric Criteria above.
3. Run `./script/check-rfc-coverage` to re-verify requirement status across `docs/rfcs/status/*.yaml`.
