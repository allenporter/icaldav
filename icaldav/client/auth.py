"""Credential storage manager for icaldav CLI and client authentication.

Stores credentials locally in ~/.config/icaldav/auth.json with strict owner-only
(0o600) permissions according to the XDG Base Directory specification.

RFC References:
  - RFC 7617: HTTP Basic Authentication.
  - RFC 6750: OAuth 2.0 Bearer Token Usage.
"""

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from urllib.parse import urlparse


@dataclass
class AuthProfile:
    """Dataclass storing authentication credentials for a CalDAV server host.

    Attributes:
        server_url: Server base URL or hostname string.
        auth_type: Authentication scheme type ('basic' or 'bearer').
        username: Optional HTTP Basic Auth username string.
        password: Optional HTTP Basic Auth password string.
        token: Optional Bearer authentication token string.
    """

    server_url: str
    auth_type: str
    username: str | None = None
    password: str | None = None
    token: str | None = None


class AuthStore:
    """Manages persistent credential storage in ~/.config/icaldav/auth.json."""

    def __init__(self, config_path: Path | None = None) -> None:
        """Initialize AuthStore with a target configuration file path.

        Args:
            config_path: Custom configuration file path or None to use default
                         (~/.config/icaldav/auth.json).
        """
        if config_path is None:
            config_path = Path.home() / ".config" / "icaldav" / "auth.json"
        self.config_path = config_path

    def _ensure_dir_and_permissions(self) -> None:
        """Create parent directory if missing and set 0o600 owner-only permissions on file."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        if self.config_path.exists():
            os.chmod(self.config_path, 0o600)

    def load_profiles(self) -> dict[str, AuthProfile]:
        """Load all credential profiles from auth.json.

        Returns:
            Dictionary mapping profile host keys to AuthProfile objects.
        """
        if not self.config_path.exists():
            return {}
        try:
            raw_data = json.loads(self.config_path.read_text(encoding="utf-8"))
            profiles: dict[str, AuthProfile] = {}
            for host, data in raw_data.items():
                profiles[host] = AuthProfile(**data)
            return profiles
        except Exception:
            return {}

    def save_credentials(
        self,
        url: str,
        username: str | None = None,
        password: str | None = None,
        token: str | None = None,
    ) -> AuthProfile:
        """Save credentials for a host or URL to auth.json.

        Args:
            url: Server URL or hostname string.
            username: Optional HTTP Basic Auth username.
            password: Optional HTTP Basic Auth password.
            token: Optional Bearer authentication token.

        Returns:
            The saved AuthProfile instance.
        """
        self._ensure_dir_and_permissions()
        profiles = self.load_profiles()

        parsed = urlparse(url)
        host_key = parsed.netloc if parsed.netloc else url.strip("/").lower()
        if not host_key:
            host_key = "default"

        auth_type = "bearer" if token else "basic"
        profile = AuthProfile(
            server_url=url,
            auth_type=auth_type,
            username=username,
            password=password,
            token=token,
        )

        profiles[host_key] = profile
        profiles["default"] = profile

        serialized = {k: asdict(v) for k, v in profiles.items()}
        self.config_path.write_text(json.dumps(serialized, indent=2), encoding="utf-8")
        os.chmod(self.config_path, 0o600)
        return profile

    def get_credentials(
        self, url: str | None = None
    ) -> tuple[str | None, str | None, str | None]:
        """Retrieve stored credentials matching a target URL or host.

        Args:
            url: Target URL to match or None to fetch default profile.

        Returns:
            Tuple of (username, password, token).
        """
        profiles = self.load_profiles()
        if not profiles:
            return None, None, None

        if url:
            parsed = urlparse(url)
            host_key = parsed.netloc if parsed.netloc else url.strip("/").lower()
            if host_key in profiles:
                p = profiles[host_key]
                return p.username, p.password, p.token

        if "default" in profiles:
            p = profiles["default"]
            return p.username, p.password, p.token

        return None, None, None

    def clear_credentials(self) -> bool:
        """Delete stored auth.json configuration file.

        Returns:
            True if file existed and was removed, False otherwise.
        """
        if self.config_path.exists():
            self.config_path.unlink()
            return True
        return False
