"""Credential storage manager for icaldav CLI and client authentication.

Stores credentials locally in ~/.config/icaldav/auth.json with strict owner-only
(0o600) permissions according to the XDG Base Directory specification.

RFC References:
  - RFC 7617: HTTP Basic Authentication.
  - RFC 6750: OAuth 2.0 Bearer Token Usage.
"""

import asyncio
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
from urllib.parse import urlparse
import aiohttp
from mashumaro.mixins.json import DataClassJSONMixin

_LOGGER = logging.getLogger(__name__)

DEFAULT_AUTH_PATH = Path.home() / ".config" / "icaldav" / "auth.json"


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

    server_url: str
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
        import time

        return time.time() >= self.token_expires_at - 300

    @property
    def basic_auth(self) -> aiohttp.BasicAuth | None:
        """Create an aiohttp.BasicAuth object if username and password are provided."""
        if self.username and self.password:
            return aiohttp.BasicAuth(self.username, self.password)
        return None


class AuthStore:
    """Manages persistent credential storage in ~/.config/icaldav/auth.json."""

    def __init__(self, config_path: Path | None = None) -> None:
        """Initialize AuthStore with a target configuration file path.

        Args:
            config_path: Custom configuration file path or None to use default
                         (DEFAULT_AUTH_PATH).
        """
        self.config_path = config_path or DEFAULT_AUTH_PATH

    def _ensure_dir(self) -> None:
        """Create parent directory if missing."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_profiles_sync(self) -> dict[str, AuthProfile]:
        """Private synchronous method to load all credential profiles from auth.json."""
        if not self.config_path.exists():
            return {}
        try:
            raw_data = json.loads(self.config_path.read_text(encoding="utf-8"))
            profiles: dict[str, AuthProfile] = {}
            for host, data in raw_data.items():
                profiles[host] = AuthProfile.from_dict(data)
            return profiles
        except (json.JSONDecodeError, KeyError, TypeError) as err:
            _LOGGER.warning("Failed to parse auth config %s: %s", self.config_path, err)
            return {}

    async def load_profiles(self) -> dict[str, AuthProfile]:
        """Asynchronously load all credential profiles off the main event loop thread."""
        return await asyncio.to_thread(self._load_profiles_sync)

    def _save_profile_sync(self, profile: AuthProfile) -> AuthProfile:
        """Private synchronous method to save an AuthProfile to auth.json."""
        self._ensure_dir()
        profiles = self._load_profiles_sync()

        parsed = urlparse(profile.server_url)
        host_key = (
            parsed.netloc if parsed.netloc else profile.server_url.strip("/").lower()
        )
        if not host_key:
            host_key = "default"

        profiles[host_key] = profile
        profiles["default"] = profile

        serialized = {k: v.to_dict() for k, v in profiles.items()}
        fd = os.open(
            str(self.config_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(serialized, f, indent=2)
        return profile

    async def save_profile(self, profile: AuthProfile) -> AuthProfile:
        """Asynchronously save an AuthProfile off the main event loop thread."""
        return await asyncio.to_thread(self._save_profile_sync, profile)

    def _get_profile_sync(self, url: str | None = None) -> AuthProfile | None:
        """Private synchronous method to retrieve stored AuthProfile matching a URL."""
        profiles = self._load_profiles_sync()
        if not profiles:
            return None

        if url:
            parsed = urlparse(url)
            host_key = parsed.netloc if parsed.netloc else url.strip("/").lower()
            if host_key in profiles:
                return profiles[host_key]

        return profiles.get("default")

    async def get_profile(self, url: str | None = None) -> AuthProfile | None:
        """Asynchronously retrieve stored AuthProfile off the main event loop thread."""
        return await asyncio.to_thread(self._get_profile_sync, url)

    def _clear_credentials_sync(self) -> bool:
        """Private synchronous method to delete stored auth.json configuration file."""
        if self.config_path.exists():
            self.config_path.unlink()
            return True
        return False

    async def clear_credentials(self) -> bool:
        """Asynchronously delete stored auth.json configuration file."""
        return await asyncio.to_thread(self._clear_credentials_sync)
