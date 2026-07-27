# Agent Handoff & Execution Blueprint

This document serves as the master onboarding and execution guide for fresh AI agents or human developers resuming work on `icaldav`.

---

## 1. Environment & Verification Quickstart

Upon starting a new session, run the single verification command:

```bash
./script/test && ./script/lint
```

This single command runs:
* All unit tests (`pytest`)
* Code quality linters (`ruff`, `ty`, `codespell`, `yamllint`)
* **Track 1 Linter**: `./script/check-architecture` (verifies layer isolation and tracks legacy imports)
* **Track 2 Coverage Reporter**: `./script/check-rfc-coverage` (verifies groundtruth requirements and production maturity)

---

## 2. Track 1: Architecture Cleanup & IR Engine (Internal Track)

* **Goal**: Decouple WebDAV HTTP route handlers from XML parsing/formatting via the 3-Layer Intermediate Representation (IR) Engine (`icaldav/engine/`).
* **Design Spec**: [architecture-design-space.md](architecture-design-space.md)
* **Roadmap & Task List**: [architecture-roadmap.md](architecture-roadmap.md)
* **Verification Tool**: `./script/check-architecture`

### Immediate Next Step for Track 1:
Begin **Phase 2 of `architecture-roadmap.md`**:
1. Create `icaldav/engine/models.py` with strongly-typed request/response IR dataclasses (`PropfindQuery`, `SyncCollectionQuery`, `CalendarQuery`, `WebDavMultiStatus`, `PropstatBlock`).
2. Create `icaldav/engine/core.py` with pure domain evaluation methods operating on storage interfaces (`LocalStore`, `PrincipalStore`).
3. Add pure domain unit tests in `tests/engine/test_core.py` (zero HTTP and zero XML dependencies).

---

## 3. Track 2: Specification Compliance & Production Maturity (External Spec Track)

* **Goal**: Fulfill all groundtruth RFC requirements (RFC 4791, 4918, 6578, 3744, 5397, 6764) and upgrade them from `prototype` to `production_grade` by passing automated compliance test suites (`litmus`, `caldavtester`).
* **Maturity Rubric**: [rfcs/RUBRIC.md](rfcs/RUBRIC.md)
* **Server Roadmap**: [server-roadmap.md](server-roadmap.md)
* **Groundtruth Requirements Database**: [rfcs/status/](rfcs/status/)
* **Mirrored RFC Texts**: [rfcs/](rfcs/)
* **Verification Tool**: `./script/check-rfc-coverage`

### Immediate Next Step for Track 2:
1. Set up an automated test runner script (e.g. `script/test-compliance`) to execute [`notroj/litmus`](https://github.com/notroj/litmus) or [`CalConnect/caldavtester`](https://github.com/CalConnect/caldavtester) against `CalDavRouter`.
2. Address known protocol gaps to upgrade requirements from `prototype` to `production_grade`:
   * Implement deleted resource tombstone tracking (404 status diff items) and multi-page token pagination in `sync-collection` REPORT (RFC 6578 §3.2, §3.7).
   * Implement persistent multi-user `PrincipalStore` backend.
   * Implement `PROPPATCH`, `COPY`, and `MOVE` HTTP methods (RFC 4918 §9.2, §9.8, §9.9).

---

## 4. Summary Status Table

| Track | Master Spec / ADR | Task Roadmap | Automated Tool | Current State |
|---|---|---|---|---|
| **Track 1: Architecture** | [architecture-design-space.md](architecture-design-space.md) | [architecture-roadmap.md](architecture-roadmap.md) | `./script/check-architecture` | Phase 1 Complete (Soft-tracking 2 legacy handler imports). |
| **Track 2: RFC Compliance** | [rfcs/RUBRIC.md](rfcs/RUBRIC.md) | [server-roadmap.md](server-roadmap.md) | `./script/check-rfc-coverage` | 76.1% Spec Coverage (35/46 reqs), 0% Prod-Grade (Awaiting `litmus` compliance runs). |
