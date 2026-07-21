"""Unit tests for OAuth 2.0 authorization support."""

import time
import urllib.parse

from aiohttp import web
from aiohttp.test_utils import TestServer

from icaldav.client.oauth import (
    OAuthConfig,
    OAuthSession,
    OAuthToken,
    discover_oauth_config,
)


def test_oauth_config_google() -> None:
    """Test OAuthConfig.google() returns correct endpoints, scopes, and redirect_uri."""
    config = OAuthConfig.google(
        client_id="test-client-id",
        client_secret="test-client-secret",
    )
    assert config.client_id == "test-client-id"
    assert config.client_secret == "test-client-secret"
    assert config.auth_uri == "https://accounts.google.com/o/oauth2/v2/auth"
    assert config.token_uri == "https://oauth2.googleapis.com/token"
    assert config.redirect_uri == "http://localhost:8088"
    assert config.scopes == ["https://www.googleapis.com/auth/calendar"]


def test_oauth_token_not_expired() -> None:
    """Test OAuthToken with expires_at far in the future is not expired."""
    token = OAuthToken(
        access_token="access-token-123",
        expires_at=time.time() + 7200,  # 2 hours from now
    )
    assert token.is_expired is False


def test_oauth_token_expired() -> None:
    """Test OAuthToken with expires_at in the past is expired."""
    token = OAuthToken(
        access_token="access-token-123",
        expires_at=time.time() - 60,  # 1 minute ago
    )
    assert token.is_expired is True


def test_oauth_token_expiring_soon() -> None:
    """Test OAuthToken expiring within 5-minute safety margin is treated as expired."""
    token = OAuthToken(
        access_token="access-token-123",
        expires_at=time.time() + 200,  # ~3 minutes from now, within 300s margin
    )
    assert token.is_expired is True


def test_oauth_token_no_expiry() -> None:
    """Test OAuthToken with no expires_at is not considered expired."""
    token = OAuthToken(
        access_token="access-token-123",
        expires_at=None,
    )
    assert token.is_expired is False


def test_authorize_url_pkce() -> None:
    """Test OAuthSession.authorize_url() generates valid PKCE authorization URL."""
    config = OAuthConfig(
        client_id="my-client-id",
        client_secret="my-client-secret",
        auth_uri="https://auth.example.com/authorize",
        token_uri="https://auth.example.com/token",
        redirect_uri="http://localhost:8088",
        scopes=["calendar.read", "calendar.write"],
    )
    url, code_verifier = OAuthSession.authorize_url(config, state="test-state")

    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "auth.example.com"
    assert parsed.path == "/authorize"
    assert params["response_type"] == ["code"]
    assert params["client_id"] == ["my-client-id"]
    assert params["redirect_uri"] == ["http://localhost:8088"]
    assert params["scope"] == ["calendar.read calendar.write"]
    assert params["state"] == ["test-state"]
    assert params["code_challenge_method"] == ["S256"]
    assert "code_challenge" in params
    assert len(params["code_challenge"][0]) > 0

    # code_verifier must be URL-safe (no +, /, = characters)
    assert len(code_verifier) > 0
    assert "+" not in code_verifier
    assert "/" not in code_verifier


async def test_exchange_code() -> None:
    """Test OAuthSession.exchange_code() posts correct data and returns valid OAuthToken."""
    received_data: dict[str, str] = {}

    async def handle_token(request: web.Request) -> web.Response:
        data = await request.post()
        received_data.update({k: str(v) for k, v in data.items()})
        return web.json_response(
            {
                "access_token": "new-access-token",
                "refresh_token": "new-refresh-token",
                "expires_in": 3600,
                "token_type": "Bearer",
            }
        )

    app = web.Application()
    app.router.add_post("/token", handle_token)

    async with TestServer(app) as server:
        token_url = str(server.make_url("/token"))
        config = OAuthConfig(
            client_id="test-client",
            client_secret="test-secret",
            auth_uri="https://auth.example.com/authorize",
            token_uri=token_url,
            redirect_uri="http://localhost:8088",
        )

        token = await OAuthSession.exchange_code(
            config, code="auth-code-123", code_verifier="verifier-456"
        )

    assert token.access_token == "new-access-token"
    assert token.refresh_token == "new-refresh-token"
    assert token.token_type == "Bearer"
    assert token.expires_at is not None
    assert token.expires_at > time.time()

    # Verify the request payload
    assert received_data["grant_type"] == "authorization_code"
    assert received_data["code"] == "auth-code-123"
    assert received_data["code_verifier"] == "verifier-456"
    assert received_data["redirect_uri"] == "http://localhost:8088"
    assert received_data["client_id"] == "test-client"
    assert received_data["client_secret"] == "test-secret"


async def test_refresh_token() -> None:
    """Test OAuthSession.refresh() preserves original refresh_token when not returned."""
    received_data: dict[str, str] = {}

    async def handle_refresh(request: web.Request) -> web.Response:
        data = await request.post()
        received_data.update({k: str(v) for k, v in data.items()})
        # Response does NOT include a new refresh_token
        return web.json_response(
            {
                "access_token": "refreshed-access-token",
                "expires_in": 3600,
                "token_type": "Bearer",
            }
        )

    app = web.Application()
    app.router.add_post("/token", handle_refresh)

    async with TestServer(app) as server:
        token_url = str(server.make_url("/token"))
        config = OAuthConfig(
            client_id="test-client",
            client_secret="test-secret",
            auth_uri="https://auth.example.com/authorize",
            token_uri=token_url,
        )

        token = await OAuthSession.refresh(
            config, refresh_token="original-refresh-token"
        )

    assert token.access_token == "refreshed-access-token"
    assert token.refresh_token == "original-refresh-token"  # preserved
    assert token.token_type == "Bearer"
    assert token.expires_at is not None

    # Verify the request payload
    assert received_data["grant_type"] == "refresh_token"
    assert received_data["refresh_token"] == "original-refresh-token"
    assert received_data["client_id"] == "test-client"
    assert received_data["client_secret"] == "test-secret"


async def test_discover_oauth_config() -> None:
    """Test discover_oauth_config() fetches and parses OpenID discovery document."""

    async def handle_discovery(request: web.Request) -> web.Response:
        return web.json_response(
            {
                "issuer": "https://auth.example.com",
                "authorization_endpoint": "https://auth.example.com/authorize",
                "token_endpoint": "https://auth.example.com/token",
            }
        )

    app = web.Application()
    app.router.add_get("/.well-known/openid-configuration", handle_discovery)

    async with TestServer(app) as server:
        issuer_url = str(server.make_url(""))
        config = await discover_oauth_config(
            issuer_url=issuer_url,
            client_id="disc-client-id",
            client_secret="disc-client-secret",
            scopes=["openid", "calendar"],
        )

    assert config.client_id == "disc-client-id"
    assert config.client_secret == "disc-client-secret"
    assert config.auth_uri == "https://auth.example.com/authorize"
    assert config.token_uri == "https://auth.example.com/token"
    assert config.scopes == ["openid", "calendar"]
