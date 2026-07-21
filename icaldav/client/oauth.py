"""OAuth 2.0 authorization support for CalDAV client authentication."""

from icaldav.client.auth.oauth import (
    OAuthConfig,
    OAuthSession,
    OAuthToken,
    discover_oauth_config,
)

__all__ = ["OAuthConfig", "OAuthSession", "OAuthToken", "discover_oauth_config"]
