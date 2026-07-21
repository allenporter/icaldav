# icaldav

[![CI](https://github.com/allenporter/icaldav/actions/workflows/test.yaml/badge.svg)](https://github.com/allenporter/icaldav/actions)
[![PyPI version](https://img.shields.io/pypi/v/icaldav.svg)](https://pypi.org/project/icaldav/)
[![Documentation](https://img.shields.io/badge/docs-allenporter.github.io%2Ficaldav-blue)](https://allenporter.github.io/icaldav/)

A modern, local-first CalDAV client engine and embeddable ASGI server for Python, powered by [`ical`](https://github.com/allenporter/ical).

`icaldav` transforms CalDAV from a notoriously brittle network protocol into a fast, reliable local synchronization pipeline. By pairing `ical`'s type-safe data processing and recurrence engine with an `asyncio`-native sync engine and embeddable server router, `icaldav` completes the Python calendar ecosystem.

For a detailed breakdown of the local-first synchronization model, dual-path sync engine, and server scope, see the [Design Document](DESIGN.md).

---

## Why `icaldav`?

Interacting with CalDAV servers in Python has historically meant navigating fragmented RFC support, heavy server-side search bugs, and complex XML queries. `icaldav` redefines CalDAV integration by adopting a **local-first synchronization architecture**:

Rather than relying on distant servers to perform complex date filtering or recurrence expansions, `icaldav` efficiently streams raw `.ics` payloads into local storage and delegates data modeling, validation, and timeline generation to `ical`.

| Feature | `icaldav` | `python-caldav` | Raw WebDAV Tools |
| :--- | :--- | :--- | :--- |
| **Async Native (`asyncio`)** | ✅ First-class (`aiohttp`) | ⚠️ Partial wrapper module | ❌ Sync only |
| **Data Engine** | ✅ `ical` (Pydantic v2) | ❌ `icalendar` / `vobject` | ❌ None (raw XML/strings) |
| **Recurrence Handling** | ✅ Local & exact (`Timeline`) | ⚠️ Relies on client (`icalendar`) | ❌ None |
| **Incremental Sync** | ✅ RFC 6578 + ETag Fallback | ⚠️ Experimental | ❌ Manual |
| **Embeddable Server** | ✅ ASGI Router included | ❌ Client only | ❌ Client only |
| **Type Safety** | ✅ Strict `py.typed` | ⚠️ In progress | ❌ None |

---

## Key Features

- **⚡ Async Client (`CalDavClient`):** Built with `asyncio` and `aiohttp` for high-performance HTTP communication and type-safe `ical` Pydantic models.
- **🔄 Resilient Sync Engine (`CalDavSyncManager`):** Supports **RFC 6578 (WebDAV Collection Synchronization)** for single-request delta fetches, with automatic **ETag fallback** for non-RFC 6578 servers (e.g. Radicale, iCloud).
- **🧩 Local-First Recurrence & Queries:** Performs time-range slicing and recurrence expansions locally via `ical`'s `Timeline`, avoiding server-side `calendar-query` bugs.
- **🚀 Embeddable ASGI Server Router (`CalDavRouter`):** Mount a minimalist CalDAV server endpoint into FastAPI, Starlette, or `aiohttp` applications to expose calendars to native iOS, macOS, or Thunderbird clients.

---

## Installation

```bash
uv add icaldav
```

Or with pip:

```bash
pip install icaldav
```

Requires Python 3.12+.

---

## Quickstart

### Syncing a Remote Calendar Down to Local Storage

```python
import asyncio
from icaldav import CalDavClient, CalDavSyncManager
from icaldav.store import SQLiteStore

async def main():
    async with CalDavClient(
        url="https://caldav.example.com",
        username="user",
        password="password",
    ) as client:
        # Discover calendar collections
        calendars = await client.get_calendars()
        calendar = calendars[0]

        # Sync events down to a local store
        store = SQLiteStore("calendar_cache.db")
        sync_manager = CalDavSyncManager(client=client, collection=calendar, store=store)
        await sync_manager.run()

        # Query locally using `ical`'s timeline
        local_calendar = await store.get_calendar()
        for event in local_calendar.timeline.today():
            print(f"{event.start}: {event.summary}")

asyncio.run(main())
```

### Embedding a CalDAV Server Endpoint

```python
from fastapi import FastAPI
from icaldav.server import CalDavRouter
from icaldav.provider import LocalCalendarProvider

app = FastAPI()

# Expose local calendars to native mobile & desktop clients
app.include_router(
    CalDavRouter(provider=LocalCalendarProvider()),
    prefix="/caldav",
)
```

---

## License

Apache-2.0
