"""OAuth 2.0 configuration and OpenID Connect discovery models."""

from __future__ import annotations

from dataclasses import dataclass, field

import aiohttp
from mashumaro.mixins.json import DataClassJSONMixin


@dataclass
class OAuthConfig(DataClassJSONMixin):
    """Configuration for an OAuth 2.0 authorization server.

    Holds the client credentials and endpoint URIs required to perform the
    OAuth 2.0 Authorization Code flow with PKCE.

    RFC References:
        - RFC 6749 Section 2.2: Client Identifier.
        - RFC 6749 Section 3.1: Authorization Endpoint.
        - RFC 6749 Section 3.2: Token Endpoint.

    Attributes:
        client_id: OAuth client identifier issued during registration.
        client_secret: OAuth client secret issued during registration.
        auth_uri: Authorization endpoint URI.
        token_uri: Token endpoint URI.
        redirect_uri: Redirect URI for receiving authorization codes.
        scopes: List of OAuth scopes to request.
    """

    client_id: str
    client_secret: str
    auth_uri: str
    token_uri: str
    redirect_uri: str = "http://localhost:8088"
    scopes: list[str] = field(default_factory=list)

    @classmethod
    def google(cls, client_id: str, client_secret: str) -> OAuthConfig:
        """Create an OAuthConfig pre-configured for Google Calendar API.

        Args:
            client_id: Google OAuth client ID from Google Cloud Console.
            client_secret: Google OAuth client secret from Google Cloud Console.

        Returns:
            OAuthConfig configured for Google Calendar.
        """
        return cls(
            client_id=client_id,
            client_secret=client_secret,
            auth_uri="https://accounts.google.com/o/oauth2/v2/auth",
            token_uri="https://oauth2.googleapis.com/token",
            redirect_uri="http://localhost:8088",
            scopes=["https://www.googleapis.com/auth/calendar"],
        )


async def discover_oauth_config(
    issuer_url: str,
    client_id: str = "",
    client_secret: str = "",
    scopes: list[str] | None = None,
) -> OAuthConfig:
    """Discover OAuth endpoints via OpenID Connect Discovery.

    Fetches the OpenID Connect Discovery document from the issuer's
    well-known configuration endpoint and constructs an OAuthConfig with
    the discovered authorization and token endpoints.

    See: https://openid.net/specs/openid-connect-discovery-1_0.html

    Args:
        issuer_url: Base URL of the OpenID Connect issuer.
        client_id: OAuth client identifier.
        client_secret: OAuth client secret.
        scopes: Optional list of OAuth scopes.

    Returns:
        OAuthConfig populated with discovered endpoints.
    """
    discovery_url = f"{issuer_url.rstrip('/')}/.well-known/openid-configuration"
    async with aiohttp.ClientSession() as session, session.get(discovery_url) as resp:
        resp.raise_for_status()
        doc = await resp.json()

    return OAuthConfig(
        client_id=client_id,
        client_secret=client_secret,
        auth_uri=doc["authorization_endpoint"],
        token_uri=doc["token_endpoint"],
        scopes=scopes or [],
    )
