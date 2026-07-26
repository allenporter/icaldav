"""Store subpackage for local persistence and principal abstractions."""

from icaldav.store.principal import (
    PrincipalInfo,
    PrincipalStore,
    SingleUserPrincipalStore,
)

__all__ = [
    "PrincipalInfo",
    "PrincipalStore",
    "SingleUserPrincipalStore",
]
