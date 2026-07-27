"""Principal models and storage abstractions for CalDAV/WebDAV autodiscovery.

RFC References:
    - RFC 3744 Section 2 & 4.2: WebDAV Access Control Protocol & DAV:principal-URL.
    - RFC 5397 Section 3: WebDAV Current Principal Extension (DAV:current-user-principal).
    - RFC 4791 Section 6.2: CalDAV Calendar Home & User Address Sets.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PrincipalInfo:
    """Principal metadata for WebDAV/CalDAV autodiscovery and scheduling.

    In WebDAV Access Control (RFC 3744 §2), a 'Principal' is a distinct network entity (such as a user,
    group, or service) that can be authenticated and granted access permissions on server resources.
    In CalDAV (RFC 4791 §6.2), principal resources act as identity hubs that map an authenticated user
    session to their calendar home collection (`CALDAV:calendar-home-set`) and calendar email addresses
    (`CALDAV:calendar-user-address-set`).
    """

    user_id: str
    """Unique account or user identifier string (plain text, e.g. 'user' or 'bernard')."""

    principal_path: str
    """Canonical WebDAV URL path to the principal resource (RFC 3744 §4.2, e.g. '/principals/user/')."""

    calendar_home_path: str
    """Base collection URL path where this user's calendar collections reside (RFC 4791 §6.2.1, e.g. '/')."""

    email: str
    """Calendar user address URI for scheduling and invitation mapping (RFC 4791 §6.2.2, e.g. 'mailto:user@localhost')."""


class PrincipalStore(Protocol):
    """Protocol for resolving PrincipalInfo metadata for authenticated users.

    Layer Separation Note:
        Authentication (verifying credentials such as passwords, HTTP Basic Auth, or OAuth tokens) is handled
        upstream by HTTP middleware or authentication handlers. The PrincipalStore layer is responsible for
        metadata lookup—resolving an authenticated `user_id` string into its corresponding PrincipalInfo.
    """

    async def get_principal(self, user_id: str | None = None) -> PrincipalInfo:
        """Resolve PrincipalInfo for a given user_id or return the default principal.

        Args:
            user_id: Optional user identifier string resolved by upstream authentication.

        Returns:
            Resolved PrincipalInfo object.

        Raises:
            KeyError: If user_id is provided but not found in the store.
        """
        ...

    async def search_principals(self, match_str: str) -> list[PrincipalInfo]:
        """Search registered principals matching substring in user_id or email.

        Args:
            match_str: Case-insensitive search substring.

        Returns:
            List of matching PrincipalInfo objects.
        """
        ...


class InMemoryPrincipalStore:
    """In-memory principal store for standalone/local deployment and multi-user testing."""

    def __init__(
        self,
        principals: list[PrincipalInfo] | None = None,
        default_user_id: str | None = None,
    ) -> None:
        """Initialize store with optional list of principals and default user ID.

        Args:
            principals: Optional initial list of PrincipalInfo objects.
            default_user_id: Optional user ID to return when get_principal() is called with user_id=None.
        """
        self._principals: dict[str, PrincipalInfo] = {}

        if principals:
            for p in principals:
                self._principals[p.user_id] = p
            self._default_user_id = default_user_id or principals[0].user_id
        else:
            default_p = PrincipalInfo(
                user_id="user",
                principal_path="/principals/user/",
                calendar_home_path="/",
                email="mailto:user@localhost",
            )
            self._principals["user"] = default_p
            self._default_user_id = "user"

    @classmethod
    def create_single_user(
        cls,
        user_id: str = "user",
        principal_path: str = "/principals/user/",
        calendar_home_path: str = "/",
        email: str = "mailto:user@localhost",
    ) -> "InMemoryPrincipalStore":
        """Factory method creating a single-user in-memory principal store.

        Args:
            user_id: Single user identifier string.
            principal_path: URL path to principal resource.
            calendar_home_path: Collection base path for calendars.
            email: Calendar user address URI.

        Returns:
            Configured InMemoryPrincipalStore instance.
        """
        p = PrincipalInfo(
            user_id=user_id,
            principal_path=principal_path,
            calendar_home_path=calendar_home_path,
            email=email,
        )
        return cls(principals=[p], default_user_id=user_id)

    def add_principal(self, principal: PrincipalInfo) -> None:
        """Register or update a PrincipalInfo entry in memory.

        Args:
            principal: PrincipalInfo instance to add.
        """
        self._principals[principal.user_id] = principal

    async def get_principal(self, user_id: str | None = None) -> PrincipalInfo:
        """Resolve PrincipalInfo by user_id or return the default principal.

        Args:
            user_id: Optional user ID to look up. If None, returns default user principal.

        Returns:
            PrincipalInfo object.

        Raises:
            KeyError: If user_id is provided but not found in the store.
        """
        target_id = user_id if user_id is not None else self._default_user_id
        if target_id not in self._principals:
            raise KeyError(f"Principal for user '{target_id}' not found")
        return self._principals[target_id]

    async def search_principals(self, match_str: str) -> list[PrincipalInfo]:
        """Search registered principals matching substring in user_id or email.

        Args:
            match_str: Case-insensitive search substring.

        Returns:
            List of matching PrincipalInfo objects.
        """
        match_lower = match_str.lower()
        return [
            p
            for p in self._principals.values()
            if match_lower in p.user_id.lower() or match_lower in p.email.lower()
        ]


# Backward compatibility alias
SingleUserPrincipalStore = InMemoryPrincipalStore
