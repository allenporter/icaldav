# Architecture Design Space & Codebase Quality Framework

This document codifies the architectural vision, decoupled Intermediate Representation (IR) engine design, and quality validation rules for `icaldav`.

---

## 1. Architectural Motivation & Vision

### Current Bottlenecks
In many legacy WebDAV implementations, HTTP request handlers parse XML payloads directly, mix business logic with web framework calls (`aiohttp.web`), and manually construct XML string outputs. This introduces several maintainability risks:
* **Fragile Handlers**: Deeply nested `if/elif/else` blocks handling XML element tags inside web route handlers.
* **Tight Serialization Coupling**: Inability to support alternative protocol formats (e.g. **jCal / RFC 7265** JSON iCalendar payloads or REST/GraphQL APIs) without rewriting handlers.
* **Difficult Domain Testing**: Testing business logic requires creating HTTP webservers or matching raw XML string snapshots rather than inspecting clean domain objects.

---

## 2. The 3-Layer Intermediate Representation (IR) Architecture

To ensure strict decoupling, `icaldav` separates WebDAV request processing into three isolated layers:

```
                       HTTP Request (aiohttp / FastAPI / ASGI)
                                          │
                                          ▼
                      ┌───────────────────────────────────────┐
                      │    Layer 1: Protocol Decoders         │
                      │    (Parses XML / jCal into Request IR)│
                      └───────────────────┬───────────────────┘
                                          │
                                          ▼ [Strongly-Typed Request IR]
                      ┌───────────────────────────────────────┐
                      │    Layer 2: Core WebDAV Engine        │
                      │    (Pure domain logic & Store diff)  │
                      └───────────────────┬───────────────────┘
                                          │
                                          ▼ [Strongly-Typed Response IR]
                      ┌───────────────────────────────────────┐
                      │    Layer 3: Protocol Encoders         │
                      │    (Renders Response IR to XML / jCal)│
                      └───────────────────────────────────────┘
```

### Layer 1: Protocol Decoders (`icaldav/xml/` and `icaldav/jcal/`)
* Responsible solely for unmarshalling incoming bytes (XML or JSON) into strongly-typed **Request IR** objects.
* Raises clean parsing exceptions (`InvalidXmlError`, `MalformedPayloadError`) before business logic is invoked.

### Layer 2: Core WebDAV Engine (`icaldav/engine/`)
* **Zero HTTP / Zero Serialization Dependency**: Accepts Request IR objects and queries/updates `LocalStore` or `PrincipalStore`.
* Returns strongly-typed **Response IR** objects (`WebDavMultiStatus`, `WebDavResourceStatus`, `PropstatBlock`).
* Can be tested in 100% pure Python domain tests with zero network or XML string matching overhead.

### Layer 3: Protocol Encoders (`icaldav/xml/` and `icaldav/jcal/`)
* Accepts Response IR objects and serializes them into the target wire format (WebDAV Multi-Status XML or jCal JSON).

---

## 3. Core IR Domain Models

### Request IR Objects
```python
@dataclass(frozen=True)
class PropfindQuery:
    target: ResourceTarget
    depth: int
    requested_props: list[PropertyTag]


@dataclass(frozen=True)
class SyncCollectionQuery:
    sync_token: str
    limit: int | None = None


@dataclass(frozen=True)
class CalendarQuery:
    comp_filter: CompFilter
    time_range: TimeRange | None = None
```

### Response IR Objects
```python
@dataclass(frozen=True)
class PropstatBlock:
    status_code: int
    properties: dict[PropertyTag, Any]


@dataclass(frozen=True)
class WebDavResourceStatus:
    href: str
    propstats: list[PropstatBlock]


@dataclass(frozen=True)
class WebDavMultiStatus:
    responses: list[WebDavResourceStatus]
```

---

## 4. Codebase Quality & Structural Validation Framework

Beyond RFC specification coverage tracking (managed in `docs/rfcs/status/`), `icaldav` enforces four code quality and structural integrity mechanisms:

### Check 1: Automated Architecture Layer Linter (`script/check-architecture`)
* **Rule 1**: Web route handlers (`icaldav/server/handlers/`) MUST NOT import `xml.etree` or construct XML elements directly. Handlers invoke decoders/encoders.
* **Rule 2**: Storage backends (`LocalStore`, `PrincipalStore`) MUST NOT import WebDAV XML models or HTTP web objects.
* **Enforcement**: Run automatically in `./script/lint`.

### Check 2: Cognitive & Cyclomatic Complexity Guardrails
* Enable `ruff` complexity rules (`C901`) with a max cognitive complexity threshold of **8** per function.
* Eliminates deeply nested `if/elif/else` dispatch logic in route handlers.

### Check 3: Pure Domain Engine Unit Testing
* Unit tests in `tests/engine/` test `CoreWebDavEngine` directly with dataclasses.
* Zero HTTP server overhead, zero XML string parsing in engine unit tests.

### Check 4: Mutation Testing (`mutmut`)
* Run mutation testing on core parsers, filters (`CompFilter`, `TimeRange`), and state diffing logic to ensure tests catch logic modifications.

---

## 5. Refactoring & Implementation Roadmap

1. **Codify Layer Boundaries**: Reference this document in `DESIGN.md` and repository README.
2. **Build AST Architecture Linter (`script/check-architecture`)**: Add layer isolation checks to `./script/lint`.
3. **Extract Core Engine (`icaldav/engine/`)**: Move WebDAV state evaluation into strongly-typed IR dataclasses.
4. **Decouple Handlers**: Refactor `propfind.py`, `report.py`, `collection.py`, and `resource.py` to route requests through the IR engine.
