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
