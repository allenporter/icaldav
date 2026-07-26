"""Unit tests for PrincipalInfo models and InMemoryPrincipalStore."""

import pytest

from icaldav.store.principal import InMemoryPrincipalStore, PrincipalInfo


@pytest.mark.asyncio
async def test_in_memory_principal_store_default() -> None:
    """Test default values of InMemoryPrincipalStore."""
    store = InMemoryPrincipalStore()
    principal = await store.get_principal()

    assert isinstance(principal, PrincipalInfo)
    assert principal.user_id == "user"
    assert principal.principal_path == "/principals/user/"
    assert principal.calendar_home_path == "/"
    assert principal.email == "mailto:user@localhost"


@pytest.mark.asyncio
async def test_in_memory_principal_store_create_single_user() -> None:
    """Test create_single_user factory method of InMemoryPrincipalStore."""
    store = InMemoryPrincipalStore.create_single_user(
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


@pytest.mark.asyncio
async def test_in_memory_principal_store_add_and_lookup() -> None:
    """Test adding multiple principals and looking up by user_id."""
    store = InMemoryPrincipalStore()
    p2 = PrincipalInfo(
        user_id="bernard",
        principal_path="/principals/bernard/",
        calendar_home_path="/calendars/bernard/",
        email="mailto:bernard@example.com",
    )
    store.add_principal(p2)

    # Default lookup returns default user
    assert (await store.get_principal()).user_id == "user"

    # Bernard lookup returns bernard
    bernard_p = await store.get_principal("bernard")
    assert bernard_p.user_id == "bernard"
    assert bernard_p.email == "mailto:bernard@example.com"


@pytest.mark.asyncio
async def test_in_memory_principal_store_not_found_raises_key_error() -> None:
    """Test that querying a non-existent user_id raises KeyError."""
    store = InMemoryPrincipalStore()
    with pytest.raises(KeyError, match="Principal for user 'unknown' not found"):
        await store.get_principal("unknown")
