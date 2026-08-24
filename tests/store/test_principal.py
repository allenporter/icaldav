"""Unit and contract tests for PrincipalInfo models, InMemoryPrincipalStore, and SQLitePrincipalStore."""

from pathlib import Path
from typing import Any

import pytest

from icaldav.store.principal import (
    InMemoryPrincipalStore,
    PrincipalInfo,
    PrincipalStore,
)
from icaldav.store.sqlite_principal import SQLitePrincipalStore


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
    assert principal.display_name is None


@pytest.mark.asyncio
async def test_in_memory_principal_store_create_single_user() -> None:
    """Test create_single_user factory method of InMemoryPrincipalStore."""
    store = InMemoryPrincipalStore.create_single_user(
        user_id="testuser",
        principal_path="/principals/testuser/",
        calendar_home_path="/testuser/",
        email="mailto:testuser@example.com",
        display_name="Test User",
    )
    principal = await store.get_principal("testuser")

    assert principal.user_id == "testuser"
    assert principal.principal_path == "/principals/testuser/"
    assert principal.calendar_home_path == "/testuser/"
    assert principal.email == "mailto:testuser@example.com"
    assert principal.display_name == "Test User"


@pytest.mark.asyncio
async def test_in_memory_principal_store_add_and_lookup() -> None:
    """Test adding multiple principals and looking up by user_id."""
    store = InMemoryPrincipalStore()
    p2 = PrincipalInfo(
        user_id="bernard",
        principal_path="/principals/bernard/",
        calendar_home_path="/calendars/bernard/",
        email="mailto:bernard@example.com",
        display_name="Bernard Marx",
    )
    store.add_principal(p2)

    # Default lookup returns default user
    assert (await store.get_principal()).user_id == "user"

    # Bernard lookup returns bernard
    bernard_p = await store.get_principal("bernard")
    assert bernard_p.user_id == "bernard"
    assert bernard_p.email == "mailto:bernard@example.com"
    assert bernard_p.display_name == "Bernard Marx"


@pytest.mark.asyncio
async def test_in_memory_principal_store_not_found_raises_key_error() -> None:
    """Test that querying a non-existent user_id raises KeyError."""
    store = InMemoryPrincipalStore()
    with pytest.raises(KeyError, match="Principal for user 'unknown' not found"):
        await store.get_principal("unknown")


@pytest.mark.asyncio
async def test_sqlite_principal_store_in_memory() -> None:
    """Test SQLitePrincipalStore with an in-memory database."""
    store = SQLitePrincipalStore.create_single_user(
        user_id="alice",
        principal_path="/principals/alice/",
        calendar_home_path="/alice/",
        email="mailto:alice@example.com",
        display_name="Alice Smith",
    )
    p = await store.get_principal()
    assert p.user_id == "alice"
    assert p.principal_path == "/principals/alice/"
    assert p.calendar_home_path == "/alice/"
    assert p.email == "mailto:alice@example.com"
    assert p.display_name == "Alice Smith"

    # Add bob
    bob = PrincipalInfo(
        user_id="bob",
        principal_path="/principals/bob/",
        calendar_home_path="/bob/",
        email="mailto:bob@example.com",
        display_name="Bob Jones",
    )
    await store.add_principal(bob)

    p_bob = await store.get_principal("bob")
    assert p_bob.user_id == "bob"
    assert p_bob.display_name == "Bob Jones"

    with pytest.raises(KeyError, match="Principal for user 'unknown' not found"):
        await store.get_principal("unknown")

    await store.close()


@pytest.mark.asyncio
async def test_sqlite_principal_store_disk_persistence(tmp_path: Path) -> None:
    """Test SQLitePrincipalStore persistence across connection re-opens."""
    db_file = tmp_path / "principals.db"

    # 1. Initialize store on disk and write initial principals
    store1 = SQLitePrincipalStore(db_path=db_file)
    p1 = PrincipalInfo(
        user_id="alice",
        principal_path="/principals/alice/",
        calendar_home_path="/calendars/alice/",
        email="mailto:alice@example.org",
        display_name="Alice Wonderland",
    )
    p2 = PrincipalInfo(
        user_id="bob",
        principal_path="/principals/bob/",
        calendar_home_path="/calendars/bob/",
        email="mailto:bob@example.org",
        display_name="Bob Builder",
    )
    await store1.add_principal(p1, is_default=True)
    await store1.add_principal(p2, is_default=False)

    # Verify lookups and searches in session 1
    alice1 = await store1.get_principal("alice")
    assert alice1.display_name == "Alice Wonderland"
    default1 = await store1.get_principal()
    assert default1.user_id == "alice"

    results_wonder = await store1.search_principals("wonder")
    assert len(results_wonder) == 1
    assert results_wonder[0].user_id == "alice"

    # Close session 1
    await store1.close()

    # 2. Re-open store with new instance on the same file
    store2 = SQLitePrincipalStore(db_path=db_file)

    # Verify principals persist
    alice2 = await store2.get_principal("alice")
    assert alice2.user_id == "alice"
    assert alice2.principal_path == "/principals/alice/"
    assert alice2.calendar_home_path == "/calendars/alice/"
    assert alice2.email == "mailto:alice@example.org"
    assert alice2.display_name == "Alice Wonderland"

    bob2 = await store2.get_principal("bob")
    assert bob2.user_id == "bob"
    assert bob2.email == "mailto:bob@example.org"
    assert bob2.display_name == "Bob Builder"

    default2 = await store2.get_principal()
    assert default2.user_id == "alice"

    # Search queries persist
    search_all = await store2.search_principals("example.org")
    assert len(search_all) == 2
    user_ids = {p.user_id for p in search_all}
    assert user_ids == {"alice", "bob"}

    search_bob = await store2.search_principals("builder")
    assert len(search_bob) == 1
    assert search_bob[0].user_id == "bob"

    # Add a 3rd user in session 2
    p3 = PrincipalInfo(
        user_id="charlie",
        principal_path="/principals/charlie/",
        calendar_home_path="/calendars/charlie/",
        email="mailto:charlie@example.org",
        display_name="Charlie Chocolate",
    )
    await store2.add_principal(p3)
    await store2.close()

    # 3. Open session 3 and verify charlie persisted
    store3 = SQLitePrincipalStore(db_path=db_file)
    charlie3 = await store3.get_principal("charlie")
    assert charlie3.user_id == "charlie"
    assert charlie3.display_name == "Charlie Chocolate"

    all_org = await store3.search_principals("example.org")
    assert len(all_org) == 3

    await store3.close()


@pytest.fixture(params=["memory", "sqlite"])
async def principal_store(request: Any) -> Any:
    """Fixture providing parameterized PrincipalStore implementations."""
    if request.param == "memory":
        store = InMemoryPrincipalStore(
            principals=[
                PrincipalInfo(
                    user_id="alice",
                    principal_path="/principals/alice/",
                    calendar_home_path="/alice/",
                    email="mailto:alice@example.com",
                    display_name="Alice Adams",
                ),
                PrincipalInfo(
                    user_id="bob",
                    principal_path="/principals/bob/",
                    calendar_home_path="/bob/",
                    email="mailto:bob@test.com",
                    display_name="Bob Barker",
                ),
                PrincipalInfo(
                    user_id="carol",
                    principal_path="/principals/carol/",
                    calendar_home_path="/carol/",
                    email="mailto:carol@domain.org",
                    display_name="Carol Clark",
                ),
            ],
            default_user_id="alice",
        )
        yield store
    elif request.param == "sqlite":
        store = SQLitePrincipalStore(
            db_path=":memory:",
            default_user_id="alice",
            initial_principals=[
                PrincipalInfo(
                    user_id="alice",
                    principal_path="/principals/alice/",
                    calendar_home_path="/alice/",
                    email="mailto:alice@example.com",
                    display_name="Alice Adams",
                ),
                PrincipalInfo(
                    user_id="bob",
                    principal_path="/principals/bob/",
                    calendar_home_path="/bob/",
                    email="mailto:bob@test.com",
                    display_name="Bob Barker",
                ),
                PrincipalInfo(
                    user_id="carol",
                    principal_path="/principals/carol/",
                    calendar_home_path="/carol/",
                    email="mailto:carol@domain.org",
                    display_name="Carol Clark",
                ),
            ],
        )
        yield store
        await store.close()


@pytest.mark.asyncio
async def test_principal_store_contract_get_principal(
    principal_store: PrincipalStore,
) -> None:
    """Contract test: get_principal resolves default user and specific users."""
    default_p = await principal_store.get_principal()
    assert default_p.user_id == "alice"
    assert default_p.principal_path == "/principals/alice/"

    bob = await principal_store.get_principal("bob")
    assert bob.user_id == "bob"
    assert bob.email == "mailto:bob@test.com"
    assert bob.display_name == "Bob Barker"

    with pytest.raises(KeyError):
        await principal_store.get_principal("nonexistent")


@pytest.mark.asyncio
async def test_principal_store_contract_search_principals(
    principal_store: PrincipalStore,
) -> None:
    """Contract test: search_principals supports case-insensitive search by user_id, email, display_name."""
    # Match by user_id
    res_id = await principal_store.search_principals("ali")
    assert len(res_id) == 1
    assert res_id[0].user_id == "alice"

    # Match by email domain
    res_domain = await principal_store.search_principals("domain.org")
    assert len(res_domain) == 1
    assert res_domain[0].user_id == "carol"

    # Match by display name (case insensitive)
    res_name = await principal_store.search_principals("barker")
    assert len(res_name) == 1
    assert res_name[0].user_id == "bob"

    # Case insensitivity test
    res_upper = await principal_store.search_principals("ALICE")
    assert len(res_upper) == 1
    assert res_upper[0].user_id == "alice"

    # No match
    res_none = await principal_store.search_principals("xyz123notfound")
    assert len(res_none) == 0
