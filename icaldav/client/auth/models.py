"""Authentication model dataclasses and enumerations for CalDAV client transport."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import time
from typing import TYPE_CHECKING, Any

import aiohttp
from mashumaro.mixins.json import DataClassJSONMixin

from icaldav.client.auth.oauth.config import OAuthConfig
from icaldav.client.auth.oauth.session import OAuthSession

if TYPE_CHECKING:
    pass


class AuthScheme(str, Enum):
    """Enumeration of supported CalDAV authentication schemes."""

    BASIC = "basic"
    BEARER = "bearer"
    OAUTH = "oauth"
    NONE = "none"
    DIGEST = "digest"
    UNKNOWN = "unknown"


@dataclass
class AuthMethod:
    """Authentication method details returned by AuthNegotiator.probe()."""

    scheme: AuthScheme
    realm: str | None = None
    oauth_config: OAuthConfig | None = None


@dataclass
class AuthProfile(DataClassJSONMixin):
    """Dataclass storing authentication credentials for a CalDAV server host.

    Attributes:
        server_url: Server base URL or hostname string.
        username: Optional HTTP Basic Auth username string.
        password: Optional HTTP Basic Auth password string.
        token: Optional Bearer authentication token string.
        client_id: Optional OAuth 2.0 client identifier string.
        client_secret: Optional OAuth 2.0 client secret string.
        refresh_token: Optional OAuth 2.0 refresh token string.
        token_uri: Optional OAuth 2.0 token endpoint URI string.
        token_expires_at: Optional Unix timestamp when the access token expires.
    """

    server_url: str = ""
    username: str | None = None
    password: str | None = None
    token: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    refresh_token: str | None = None
    token_uri: str | None = None
    token_expires_at: float | None = None

    @property
    def auth_type(self) -> str:
        """Dynamically computed authentication scheme type ('oauth', 'bearer', or 'basic')."""
        if self.refresh_token:
            return "oauth"
        if self.token:
            return "bearer"
        return "basic"

    @property
    def is_token_expired(self) -> bool:
        """Check if the stored OAuth access token has expired (with 5-minute safety margin)."""
        if self.token_expires_at is None:
            return True

        return time.time() >= self.token_expires_at - 300

    @property
    def basic_auth(self) -> aiohttp.BasicAuth | None:
        """Create an aiohttp.BasicAuth object if username and password are provided."""
        if self.username and self.password:
            return aiohttp.BasicAuth(self.username, self.password)
        return None

    async def ensure_fresh_token(self) -> str | None:
        """Auto-refresh OAuth access token if expired (RFC 6749 Section 6)."""
        if self.auth_type != "oauth":
            return self.token
        if self.token and not self.is_token_expired:
            return self.token

        config = OAuthConfig(
            client_id=self.client_id or "",
            client_secret=self.client_secret or "",
            auth_uri="",
            token_uri=self.token_uri or "",
        )
        fresh_token = await OAuthSession.refresh(config, self.refresh_token or "")
        self.token = fresh_token.access_token
        self.token_expires_at = fresh_token.expires_at
        return self.token

    async def get_session_kwargs(self) -> dict[str, Any]:
        """Returns kwargs dictionary (auth, headers) for initializing an aiohttp.ClientSession."""
        if self.auth_type == "basic":
            if self.basic_auth:
                return {"auth": self.basic_auth}
            return {}

        token = await self.ensure_fresh_token()
        if token:
            return {"headers": {"Authorization": f"Bearer {token}"}}

        return {}
