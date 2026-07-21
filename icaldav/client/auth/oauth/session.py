"""OAuth 2.0 PKCE session token operations and local callback listener."""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
import urllib.parse
from dataclasses import dataclass

import aiohttp
from mashumaro.mixins.json import DataClassJSONMixin

from icaldav.client.auth.oauth.config import OAuthConfig


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
        """Check whether the access token has expired or will expire soon (5-minute safety margin)."""
        if self.expires_at is None:
            return False
        return time.time() >= self.expires_at - 300


class OAuthSession:
    """OAuth 2.0 Authorization Code flow operations with PKCE support.

    RFC References:
        - RFC 6749 Section 4.1: Authorization Code Grant.
        - RFC 7636: Proof Key for Code Exchange (PKCE).
        - RFC 6750: Bearer Token Usage.
    """

    @staticmethod
    def authorize_url(config: OAuthConfig, state: str | None = None) -> tuple[str, str]:
        """Build an OAuth 2.0 authorization URL with PKCE challenge (RFC 7636).

        Args:
            config: OAuth configuration with endpoint URIs and client info.
            state: Optional opaque state value for CSRF protection.

        Returns:
            Tuple of (authorization_url, code_verifier).
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

        Args:
            config: OAuth configuration.
            code: Authorization code from server redirect.
            code_verifier: PKCE code verifier.

        Returns:
            OAuthToken instance containing tokens and expiration time.
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

        Args:
            config: OAuth configuration.
            refresh_token: Stored refresh token string.

        Returns:
            OAuthToken with fresh access token.
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

    @staticmethod
    async def fetch_code_from_callback(port: int = 8088, timeout: float = 300.0) -> str:
        """Start a temporary local HTTP server to receive the OAuth authorization code redirect.

        Args:
            port: Local TCP port for the callback server (default 8088).
            timeout: Maximum seconds to wait for redirect (default 300s).

        Returns:
            Extracted authorization code string.
        """
        import asyncio
        from aiohttp import web

        code_future: asyncio.Future[str] = asyncio.get_running_loop().create_future()

        async def handle_callback(request: web.Request) -> web.Response:
            code = request.query.get("code")
            error = request.query.get("error")
            if error:
                code_future.set_exception(Exception(f"OAuth error: {error}"))
                return web.Response(
                    text="Authorization failed. You can close this tab.",
                    content_type="text/plain",
                )
            if code:
                code_future.set_result(code)
                return web.Response(
                    text="Authorization successful! You can close this tab.",
                    content_type="text/plain",
                )
            return web.Response(
                text="Missing authorization code.",
                status=400,
                content_type="text/plain",
            )

        app = web.Application()
        app.router.add_get("/", handle_callback)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "localhost", port)
        await site.start()

        try:
            return await asyncio.wait_for(code_future, timeout=timeout)
        finally:
            await runner.cleanup()
