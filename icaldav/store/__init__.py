"""Store subpackage for local persistence and principal abstractions."""

from icaldav.store.memory import MemoryStore
from icaldav.store.principal import (
    InMemoryPrincipalStore,
    PrincipalInfo,
    PrincipalStore,
    SingleUserPrincipalStore,
)
from icaldav.store.sqlite import SQLiteStore
from icaldav.store.sqlite_principal import SQLitePrincipalStore
from icaldav.store.types import (
    CalendarResource,
    CollectionPath,
    LocalStore,
    ResourceKind,
    ResourcePath,
    ResourceTarget,
    SyncChanges,
    SyncToken,
)

__all__ = [
    "CalendarResource",
    "CollectionPath",
    "InMemoryPrincipalStore",
    "LocalStore",
    "MemoryStore",
    "PrincipalInfo",
    "PrincipalStore",
    "ResourceKind",
    "ResourcePath",
    "ResourceTarget",
    "SQLitePrincipalStore",
    "SQLiteStore",
    "SingleUserPrincipalStore",
    "SyncChanges",
    "SyncToken",
]
