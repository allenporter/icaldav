"""
.. include:: ../README.md
"""

from icaldav.client.client import CalDavClient
from icaldav.client.sync import CalDavSyncManager, SyncPath, SyncResult

__all__ = [
    "CalDavClient",
    "CalDavSyncManager",
    "SyncPath",
    "SyncResult",
]
