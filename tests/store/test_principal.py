"""Unit tests for PrincipalInfo models and SingleUserPrincipalStore."""

import pytest

from icaldav.store.principal import PrincipalInfo, SingleUserPrincipalStore


@pytest.mark.asyncio
async def test_single_user_principal_store_default() -> None:
    """Test default values of SingleUserPrincipalStore."""
    store = SingleUserPrincipalStore()
    principal = await store.get_principal()

    assert isinstance(principal, PrincipalInfo)
    assert principal.user_id == "user"
    assert principal.principal_path == "/principals/user/"
    assert principal.calendar_home_path == "/"
    assert principal.email == "mailto:user@localhost"


@pytest.mark.asyncio
async def test_single_user_principal_store_custom() -> None:
    """Test custom values of SingleUserPrincipalStore."""
    store = SingleUserPrincipalStore(
        user_id="testuser",
        principal_path="/principals/testuser/",
        calendar_home_path="/testuser/",
        email="mailto:testuser@example.com",
    )
    principal = await store.get_principal("testuser")

    assert principal.user_id == "testuser"
    assert principal.principal_path == "/principals/testuser/"
    assert principal.calendar_home_path == "/testuser/"
    assert principal.email == "mailto:testuser@example.com"
