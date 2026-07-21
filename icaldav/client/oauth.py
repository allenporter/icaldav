"""OAuth 2.0 authorization support for CalDAV client authentication.

Provides OAuth 2.0 Authorization Code flow with PKCE (Proof Key for Code
Exchange) for secure client authentication against CalDAV servers that support
OAuth, such as Google Calendar.

RFC References:
  - RFC 6749: The OAuth 2.0 Authorization Framework.
  - RFC 7636: Proof Key for Code Exchange by OAuth Public Clients (PKCE).
  - RFC 6750: The OAuth 2.0 Authorization Framework: Bearer Token Usage.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
import urllib.parse
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

        Uses Google's OAuth 2.0 endpoints and the default Calendar read/write
        scope.

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
        issuer_url: Base URL of the OpenID Connect issuer (e.g.
            ``https://accounts.google.com``). Trailing slashes are stripped.
        client_id: OAuth client identifier.
        client_secret: OAuth client secret.
        scopes: Optional list of OAuth scopes. Defaults to an empty list.

    Returns:
        OAuthConfig populated with discovered endpoints.

    Raises:
        aiohttp.ClientResponseError: If the discovery endpoint returns
            a non-200 HTTP status.
        KeyError: If the discovery document is missing required fields.
    """
    discovery_url = f"{issuer_url.rstrip('/')}/.well-known/openid-configuration"
    async with aiohttp.ClientSession() as session:
        async with session.get(discovery_url) as resp:
            resp.raise_for_status()
            doc = await resp.json()

    return OAuthConfig(
        client_id=client_id,
        client_secret=client_secret,
        auth_uri=doc["authorization_endpoint"],
        token_uri=doc["token_endpoint"],
        scopes=scopes or [],
    )


@dataclass
class OAuthToken(DataClassJSONMixin):
    """OAuth 2.0 access token with optional refresh capability.

    RFC References:
        - RFC 6749 Section 5.1: Successful Response (access token).
        - RFC 6749 Section 6: Refreshing an Access Token.
        - RFC 6750 Section 1: Bearer Token Usage overview.

    Attributes:
        access_token: The access token string.
        refresh_token: Optional refresh token for obtaining new access tokens.
        expires_at: Optional UNIX timestamp when the access token expires.
        token_type: Token type, typically ``Bearer``.
    """

    access_token: str
    refresh_token: str | None = None
    expires_at: float | None = None
    token_type: str = "Bearer"

    @property
    def is_expired(self) -> bool:
        """Check whether the access token has expired or will expire soon.

        Uses a 300-second (5-minute) safety margin to allow time for token
        refresh before the actual expiration.

        Returns:
            True if ``expires_at`` is set and the current time is within
            5 minutes of expiration. False if ``expires_at`` is not set.
        """
        if self.expires_at is None:
            return False
        return time.time() >= self.expires_at - 300


class OAuthSession:
    """OAuth 2.0 Authorization Code flow operations with PKCE support.

    Provides methods for building authorization URLs, exchanging authorization
    codes for tokens, and refreshing expired tokens.

    RFC References:
        - RFC 6749 Section 4.1: Authorization Code Grant.
        - RFC 7636: Proof Key for Code Exchange (PKCE).
        - RFC 6750: Bearer Token Usage.
    """

    @staticmethod
    def authorize_url(config: OAuthConfig, state: str | None = None) -> tuple[str, str]:
        """Build an OAuth 2.0 authorization URL with PKCE challenge.

        Generates a cryptographically random ``code_verifier`` and derives the
        ``code_challenge`` using the S256 method as specified in RFC 7636.

        RFC References:
            - RFC 6749 Section 4.1.1: Authorization Request.
            - RFC 7636 Section 4.1: Client Creates a Code Verifier.
            - RFC 7636 Section 4.2: Client Creates the Code Challenge.

        Args:
            config: OAuth configuration with endpoint URIs and client info.
            state: Optional opaque state value for CSRF protection
                (RFC 6749 Section 10.12). If None, a random value is generated.

        Returns:
            A tuple of ``(authorization_url, code_verifier)`` where the URL
            should be opened in a browser and the verifier must be preserved
            for the subsequent ``exchange_code`` call.
        """
        code_verifier = secrets.token_urlsafe(96)[:128]

        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

        if state is None:
            state = secrets.token_urlsafe(32)

        params = {
            "response_type": "code",
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "scope": " ".join(config.scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
        }
        authorization_url = f"{config.auth_uri}?{urllib.parse.urlencode(params)}"
        return authorization_url, code_verifier

    @staticmethod
    async def exchange_code(
        config: OAuthConfig, code: str, code_verifier: str
    ) -> OAuthToken:
        """Exchange an authorization code for access and refresh tokens.

        Sends a POST request to the token endpoint with the authorization
        code and PKCE code verifier to obtain tokens.

        RFC References:
            - RFC 6749 Section 4.1.3: Access Token Request.
            - RFC 7636 Section 4.5: Client Sends the Code Verifier.

        Args:
            config: OAuth configuration with endpoint URIs and client info.
            code: Authorization code received from the authorization server.
            code_verifier: PKCE code verifier generated during authorization.

        Returns:
            OAuthToken containing the access token and optional refresh token.

        Raises:
            aiohttp.ClientResponseError: If the token endpoint returns a
                non-200 HTTP status.
        """
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": config.redirect_uri,
            "client_id": config.client_id,
            "client_secret": config.client_secret,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(config.token_uri, data=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()

        expires_at: float | None = None
        if "expires_in" in data:
            expires_at = time.time() + float(data["expires_in"])

        return OAuthToken(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=expires_at,
            token_type=data.get("token_type", "Bearer"),
        )

    @staticmethod
    async def refresh(config: OAuthConfig, refresh_token: str) -> OAuthToken:
        """Refresh an expired access token using a refresh token.

        Sends a POST request to the token endpoint with the refresh token
        to obtain a new access token. The response may or may not include
        a new refresh token; if absent, the original refresh token is
        preserved in the returned OAuthToken.

        RFC References:
            - RFC 6749 Section 6: Refreshing an Access Token.

        Args:
            config: OAuth configuration with endpoint URIs and client info.
            refresh_token: The refresh token from a previous token response.

        Returns:
            OAuthToken with a fresh access token and the original or new
            refresh token.

        Raises:
            aiohttp.ClientResponseError: If the token endpoint returns a
                non-200 HTTP status.
        """
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": config.client_id,
            "client_secret": config.client_secret,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(config.token_uri, data=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()

        expires_at: float | None = None
        if "expires_in" in data:
            expires_at = time.time() + float(data["expires_in"])

        return OAuthToken(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", refresh_token),
            expires_at=expires_at,
            token_type=data.get("token_type", "Bearer"),
        )
