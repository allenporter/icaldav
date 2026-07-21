"""CalDAV client authentication, credential persistence, negotiation, and OAuth support."""

from icaldav.client.auth.models import AuthMethod, AuthProfile, AuthScheme
from icaldav.client.auth.negotiator import AuthNegotiator, KNOWN_OAUTH_ISSUERS
from icaldav.client.auth.oauth import (
    OAuthConfig,
    OAuthSession,
    OAuthToken,
    discover_oauth_config,
)
from icaldav.client.auth.store import DEFAULT_AUTH_PATH, AuthStore

__all__ = [
    "DEFAULT_AUTH_PATH",
    "AuthMethod",
    "AuthNegotiator",
    "OAuthConfig",
    "AuthProfile",
    "AuthScheme",
    "OAuthSession",
    "AuthStore",
    "OAuthToken",
    "KNOWN_OAUTH_ISSUERS",
    "discover_oauth_config",
]
