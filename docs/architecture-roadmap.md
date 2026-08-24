# Architecture Refactoring Roadmap & Task List

Progress tracking and task breakdown for decoupling WebDAV handlers from XML serialization via the Intermediate Representation (IR) Engine (`icaldav/engine/`).

---

## 1. Refactoring Goals
1. **Decouple Handlers from XML**: Handlers in `icaldav/server/handlers/` MUST NOT import `xml.etree` or parse/format XML strings directly.
2. **Introduce Core WebDAV Engine (`icaldav/engine/`)**: Pure domain logic operating on strongly-typed Request/Response IR dataclasses with **zero HTTP and zero XML dependencies**.
3. **Pluggable Serialization**: Support swapping XML serializers (`icaldav/xml/`) for alternative wire formats (e.g. **jCal / RFC 7265** JSON iCalendar payloads).
4. **Zero New Architecture Violations**: Enforce layer isolation using `./script/check-architecture` in CI.

---

## 2. Phase Breakdown & Task List

### Phase 1: Foundation & Boundary Isolation (Completed)
- [x] **ADR & Design Space Document**: Codified 3-layer decoupled pipeline in `docs/architecture-design-space.md`.
- [x] **AST Architecture Linter (`script/check-architecture`)**: Built automated linter integrated into `./script/lint`.
- [x] **Legacy Violation Tracking**: Configured soft-allowlist tracking 2 legacy handler imports (`propfind.py`, `report.py`) while blocking new violations.

### Phase 2: Core Intermediate Representation (IR) Engine (`icaldav/engine/`)
- [ ] **Create Core Engine Models (`icaldav/engine/models.py`)**:
  - Define `PropfindQuery`, `SyncCollectionQuery`, `CalendarQuery`, `CalendarMultigetQuery`, and `PrincipalSearchQuery` request dataclasses.
  - Define `WebDavMultiStatus`, `WebDavResourceStatus`, and `PropstatBlock` response dataclasses.
- [ ] **Create Core WebDAV Engine (`icaldav/engine/core.py`)**:
  - Implement `evaluate_propfind()`, `evaluate_calendar_query()`, `evaluate_calendar_multiget()`, `evaluate_sync_collection()`, and `evaluate_principal_search()`.
  - Ensure methods operate purely on dataclasses and `LocalStore`/`PrincipalStore` interfaces.
- [ ] **Pure Engine Unit Tests (`tests/engine/`)**:
  - Add domain tests for `CoreWebDavEngine` testing store interactions without HTTP or XML string matching.

### Phase 3: Protocol Decoders & Encoders Refactoring (`icaldav/xml/`)
- [ ] **Decouple XML Root Tag Inspection**:
  - Create `parse_report_root_tag(xml_bytes)` in `icaldav/xml/report/request.py`.
  - Create `parse_propfind_root_tag(xml_bytes)` in `icaldav/xml/propfind/request.py`.
- [ ] **Encapsulate XML Response Formatting**:
  - Move XML multi-status element generation entirely into `icaldav/xml/propfind/response.py` and `icaldav/xml/report/response.py`.

### Phase 4: Handler Refactoring & Violation Elimination
- [ ] **Refactor `PropfindHandler` (`icaldav/server/handlers/propfind.py`)**:
  - Remove direct `xml.etree` imports (`import xml.etree.ElementTree as ET`).
  - Route incoming requests through `parse_propfind_request()` -> `engine.evaluate_propfind()` -> `build_propfind_xml()`.
- [ ] **Refactor `ReportHandler` (`icaldav/server/handlers/report.py`)**:
  - Remove direct `xml.etree` imports (`import xml.etree.ElementTree as ET`).
  - Route incoming requests through `parse_report_request()` -> `engine.evaluate_report()` -> `build_report_xml()`.
- [ ] **Eliminate Allowlist in `script/check-architecture`**:
  - Remove `KNOWN_LEGACY_XML_HANDLERS` allowlist in `script/check-architecture`, enforcing 0 architecture violations across the entire codebase.

### Phase 5: Alternative Serializer Readiness (jCal / RFC 7265)
- [x] **Validate Serializer Swap**:
  - Implement prototype jCal encoder (`icaldav/jcal/`) to verify that `CoreWebDavEngine` IR objects render to JSON payloads without engine or handler changes.

---

## 3. Progress Metric

| Phase | Description | Status |
|---|---|---|
| **Phase 1** | Foundation & Boundary Isolation | **100% Complete** |
| **Phase 2** | Core IR Engine (`icaldav/engine/`) | **0% (Next Up)** |
| **Phase 3** | Decoders & Encoders Refactoring (`icaldav/xml/`) | **0%** |
| **Phase 4** | Handler Refactoring & 0 Violations | **0%** |
| **Phase 5** | Alternative Serializer Readiness (jCal) | **100% Complete** |
