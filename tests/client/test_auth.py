"""Unit tests for AuthStore credential manager."""

from pathlib import Path

import pytest

from icaldav.client.auth import DEFAULT_AUTH_PATH, AuthProfile, AuthStore


@pytest.mark.asyncio
async def test_auth_store_save_and_retrieve(tmp_path: Path) -> None:
    """Test saving AuthProfile objects and retrieving them by host matching and default fallback."""
    config_file = tmp_path / "auth.json"
    auth_store = AuthStore(config_file)

    # 1. Default path fallback check
    default_store = AuthStore()
    assert default_store.config_path == DEFAULT_AUTH_PATH

    # 2. Initially empty
    profile = await auth_store.get_profile("https://caldav.fastmail.com/work")
    assert profile is None

    # 3. Save basic profile
    p1 = AuthProfile(
        server_url="https://caldav.fastmail.com",
        username="alice@example.com",
        password="secretpassword",
    )
    assert p1.auth_type == "basic"

    saved_p1 = await auth_store.save_profile(p1)
    assert saved_p1.username == "alice@example.com"

    # 4. Retrieve matching host
    profile = await auth_store.get_profile("https://caldav.fastmail.com/calendars/user")
    assert profile is not None
    assert profile.username == "alice@example.com"
    assert profile.password == "secretpassword"
    assert profile.token is None
    assert profile.auth_type == "basic"

    # 5. Default fallback retrieval
    profile = await auth_store.get_profile()
    assert profile is not None
    assert profile.username == "alice@example.com"

    # 6. File permissions check (owner read/write 0o600)
    mode = oct(config_file.stat().st_mode & 0o777)
    assert mode == "0o600"

    # 7. Save Bearer token profile using save_profile
    p2 = AuthProfile(
        server_url="https://apidata.googleusercontent.com/caldav/v2/",
        token="ya29.testtoken123",
    )
    assert p2.auth_type == "bearer"

    await auth_store.save_profile(p2)
    profile = await auth_store.get_profile(
        "https://apidata.googleusercontent.com/caldav/v2/"
    )
    assert profile is not None
    assert profile.username is None
    assert profile.token == "ya29.testtoken123"
    assert profile.auth_type == "bearer"

    # 8. Clear credentials
    assert await auth_store.clear_credentials() is True
    assert config_file.exists() is False

    # 9. Clear credentials when file already deleted returns False
    assert await auth_store.clear_credentials() is False


@pytest.mark.asyncio
async def test_auth_store_corrupted_json(tmp_path: Path) -> None:
    """Test loading profiles from corrupted auth.json returns empty dict gracefully."""
    config_file = tmp_path / "auth.json"
    config_file.write_text("{ invalid json payload }", encoding="utf-8")
    auth_store = AuthStore(config_file)

    profiles = await auth_store.load_profiles()
    assert profiles == {}


@pytest.mark.asyncio
async def test_auth_store_empty_url(tmp_path: Path) -> None:
    """Test saving profile with empty server_url falls back to default key."""
    config_file = tmp_path / "auth.json"
    auth_store = AuthStore(config_file)

    p = AuthProfile(server_url="", username="bob")
    await auth_store.save_profile(p)
    retrieved = await auth_store.get_profile()
    assert retrieved is not None
    assert retrieved.username == "bob"


@pytest.mark.asyncio
async def test_auth_profile_oauth_type(tmp_path: Path) -> None:
    """Test AuthProfile returns 'oauth' auth_type when refresh_token is set."""
    profile = AuthProfile(
        server_url="https://apidata.googleusercontent.com/caldav/v2/",
        token="ya29.access_token_here",
        client_id="test-client-id",
        client_secret="test-client-secret",
        refresh_token="1//refresh_token_here",
        token_uri="https://oauth2.googleapis.com/token",
        token_expires_at=9999999999.0,
    )
    assert profile.auth_type == "oauth"
    assert profile.is_token_expired is False


@pytest.mark.asyncio
async def test_auth_profile_oauth_expired(tmp_path: Path) -> None:
    """Test is_token_expired returns True for expired OAuth tokens."""
    profile = AuthProfile(
        server_url="https://example.com",
        token="expired_token",
        refresh_token="refresh",
        token_expires_at=0.0,  # epoch = long expired
    )
    assert profile.is_token_expired is True


@pytest.mark.asyncio
async def test_auth_store_oauth_profile_persistence(tmp_path: Path) -> None:
    """Test saving and loading AuthProfile with OAuth fields."""
    config_file = tmp_path / "auth.json"
    auth_store = AuthStore(config_file)

    profile = AuthProfile(
        server_url="https://apidata.googleusercontent.com/caldav/v2/",
        token="ya29.test_access_token",
        client_id="123456.apps.googleusercontent.com",
        client_secret="GOCSPX-secret",
        refresh_token="1//refresh_token",
        token_uri="https://oauth2.googleapis.com/token",
        token_expires_at=1700000000.0,
    )
    await auth_store.save_profile(profile)

    loaded = await auth_store.get_profile(
        "https://apidata.googleusercontent.com/caldav/v2/user@gmail.com/events"
    )
    assert loaded is not None
    assert loaded.auth_type == "oauth"
    assert loaded.client_id == "123456.apps.googleusercontent.com"
    assert loaded.client_secret == "GOCSPX-secret"
    assert loaded.refresh_token == "1//refresh_token"
    assert loaded.token_uri == "https://oauth2.googleapis.com/token"
    assert loaded.token_expires_at == 1700000000.0
    assert loaded.token == "ya29.test_access_token"
