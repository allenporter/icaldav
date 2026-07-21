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
import os
from pathlib import Path
from urllib.parse import urlparse
from mashumaro.mixins.json import DataClassJSONMixin

DEFAULT_AUTH_PATH = Path.home() / ".config" / "icaldav" / "auth.json"


@dataclass
class AuthProfile(DataClassJSONMixin):
    """Dataclass storing authentication credentials for a CalDAV server host.

    Attributes:
        server_url: Server base URL or hostname string.
        username: Optional HTTP Basic Auth username string.
        password: Optional HTTP Basic Auth password string.
        token: Optional Bearer authentication token string.
    """

    server_url: str
    username: str | None = None
    password: str | None = None
    token: str | None = None

    @property
    def auth_type(self) -> str:
        """Dynamically computed authentication scheme type ('bearer' or 'basic')."""
        return "bearer" if self.token else "basic"


class AuthStore:
    """Manages persistent credential storage in ~/.config/icaldav/auth.json."""

    def __init__(self, config_path: Path | None = None) -> None:
        """Initialize AuthStore with a target configuration file path.

        Args:
            config_path: Custom configuration file path or None to use default
                         (DEFAULT_AUTH_PATH).
        """
        self.config_path = config_path or DEFAULT_AUTH_PATH

    def _ensure_dir_and_permissions(self) -> None:
        """Create parent directory if missing and set 0o600 owner-only permissions on file."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        if self.config_path.exists():
            os.chmod(self.config_path, 0o600)

    def load_profiles(self) -> dict[str, AuthProfile]:
        """Synchronously load all credential profiles from auth.json using mashumaro.

        Returns:
            Dictionary mapping profile host keys to AuthProfile objects.
        """
        if not self.config_path.exists():
            return {}
        try:
            raw_data = json.loads(self.config_path.read_text(encoding="utf-8"))
            profiles: dict[str, AuthProfile] = {}
            for host, data in raw_data.items():
                profiles[host] = AuthProfile.from_dict(data)
            return profiles
        except Exception:
            return {}

    async def async_load_profiles(self) -> dict[str, AuthProfile]:
        """Asynchronously load all credential profiles off the main event loop thread."""
        return await asyncio.to_thread(self.load_profiles)

    def save_profile(self, profile: AuthProfile) -> AuthProfile:
        """Synchronously save an AuthProfile for a host or URL to auth.json using mashumaro.

        Args:
            profile: Target AuthProfile instance to persist.

        Returns:
            The persisted AuthProfile instance.
        """
        self._ensure_dir_and_permissions()
        profiles = self.load_profiles()

        parsed = urlparse(profile.server_url)
        host_key = (
            parsed.netloc if parsed.netloc else profile.server_url.strip("/").lower()
        )
        if not host_key:
            host_key = "default"

        profiles[host_key] = profile
        profiles["default"] = profile

        serialized = {k: v.to_dict() for k, v in profiles.items()}
        self.config_path.write_text(json.dumps(serialized, indent=2), encoding="utf-8")
        os.chmod(self.config_path, 0o600)
        return profile

    async def async_save_profile(self, profile: AuthProfile) -> AuthProfile:
        """Asynchronously save an AuthProfile off the main event loop thread."""
        return await asyncio.to_thread(self.save_profile, profile)

    def get_profile(self, url: str | None = None) -> AuthProfile | None:
        """Synchronously retrieve stored AuthProfile matching a target URL or host.

        Args:
            url: Target URL to match or None to fetch default profile.

        Returns:
            Matching AuthProfile or None if no matching profile is found.
        """
        profiles = self.load_profiles()
        if not profiles:
            return None

        if url:
            parsed = urlparse(url)
            host_key = parsed.netloc if parsed.netloc else url.strip("/").lower()
            if host_key in profiles:
                return profiles[host_key]

        return profiles.get("default")

    async def async_get_profile(self, url: str | None = None) -> AuthProfile | None:
        """Asynchronously retrieve stored AuthProfile off the main event loop thread."""
        return await asyncio.to_thread(self.get_profile, url)

    def clear_credentials(self) -> bool:
        """Synchronously delete stored auth.json configuration file.

        Returns:
            True if file existed and was removed, False otherwise.
        """
        if self.config_path.exists():
            self.config_path.unlink()
            return True
        return False

    async def async_clear_credentials(self) -> bool:
        """Asynchronously delete stored auth.json configuration file."""
        return await asyncio.to_thread(self.clear_credentials)
