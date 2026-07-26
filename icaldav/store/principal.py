"""Principal models and storage abstractions for CalDAV/WebDAV autodiscovery.

RFC References:
    - RFC 5397 Section 3: DAV:current-user-principal.
    - RFC 4791 Section 6.2.1: CALDAV:calendar-home-set.
    - RFC 3744 Section 4.2: DAV:principal-URL.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PrincipalInfo:
    """Principal metadata for WebDAV/CalDAV autodiscovery and scheduling.

    Attributes:
        user_id: Unique account or user identifier string.
        principal_path: Canonical URL path to the principal resource (e.g., "/principals/user/").
        calendar_home_path: Base collection URL path where calendar collections reside (e.g., "/").
        email: Calendar user address URI (e.g., "mailto:user@localhost").
    """

    user_id: str
    principal_path: str
    calendar_home_path: str
    email: str


class PrincipalStore(Protocol):
    """Protocol for resolving PrincipalInfo metadata."""

    async def get_principal(self, user_id: str | None = None) -> PrincipalInfo:
        """Resolve PrincipalInfo for a given user_id or return default single-user principal.

        Args:
            user_id: Optional user identifier string from request context.

        Returns:
            Resolved PrincipalInfo object.
        """
        ...


class SingleUserPrincipalStore:
    """Default single-user principal store for standalone/local server deployment."""

    def __init__(
        self,
        user_id: str = "user",
        principal_path: str = "/principals/user/",
        calendar_home_path: str = "/",
        email: str = "mailto:user@localhost",
    ) -> None:
        self._principal = PrincipalInfo(
            user_id=user_id,
            principal_path=principal_path,
            calendar_home_path=calendar_home_path,
            email=email,
        )

    async def get_principal(self, user_id: str | None = None) -> PrincipalInfo:
        """Return the single-user PrincipalInfo.

        Note:
            # TODO(multi-user): Look up user-specific PrincipalInfo from user database/store when user_id is provided.
        """
        return self._principal
