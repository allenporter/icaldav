"""Unit tests for AuthStore credential manager."""

from pathlib import Path

from icaldav.client.auth import AuthStore


def test_auth_store_save_and_retrieve(tmp_path: Path) -> None:
    """Test saving credentials and loading them back by host matching and default fallback."""
    config_file = tmp_path / "auth.json"
    auth_store = AuthStore(config_file)

    # 1. Initially empty
    user, pwd, tok = auth_store.get_credentials("https://caldav.fastmail.com/work")
    assert user is None
    assert pwd is None
    assert tok is None

    # 2. Save basic credentials
    auth_store.save_credentials(
        url="https://caldav.fastmail.com",
        username="alice@example.com",
        password="secretpassword",
    )

    # 3. Retrieve matching host
    user, pwd, tok = auth_store.get_credentials(
        "https://caldav.fastmail.com/calendars/user"
    )
    assert user == "alice@example.com"
    assert pwd == "secretpassword"
    assert tok is None

    # 4. Default fallback retrieval
    user, pwd, tok = auth_store.get_credentials()
    assert user == "alice@example.com"
    assert pwd == "secretpassword"

    # 5. File permissions check (owner read/write 0o600)
    mode = oct(config_file.stat().st_mode & 0o777)
    assert mode == "0o600"

    # 6. Save Bearer token
    auth_store.save_credentials(
        url="https://apidata.googleusercontent.com/caldav/v2/",
        token="ya29.testtoken123",
    )
    user, pwd, tok = auth_store.get_credentials(
        "https://apidata.googleusercontent.com/caldav/v2/"
    )
    assert user is None
    assert pwd is None
    assert tok == "ya29.testtoken123"

    # 7. Clear credentials
    assert auth_store.clear_credentials() is True
    assert config_file.exists() is False
