"""Unit tests for the icaldav CLI module."""

from pathlib import Path
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient, TestServer

from icaldav.cli import build_parser, main, main_async
from icaldav.client.auth import AuthStore
from icaldav.server.router import create_app
from icaldav.store.memory import MemoryStore


def test_cli_parser_help(capsys: pytest.CaptureFixture[str]) -> None:
    """Test top-level CLI help command output."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "icaldav CLI" in captured.out
    assert "serve" in captured.out
    assert "client" in captured.out
    assert "store" in captured.out
    assert "auth" in captured.out


def test_cli_parser_subcommands() -> None:
    """Test argument parsing for all subcommands."""
    parser = build_parser()

    # serve
    args = parser.parse_args(["serve", "--port", "9090"])
    assert args.command == "serve"
    assert args.port == 9090

    # client propfind with auth flags
    args = parser.parse_args(
        [
            "client",
            "propfind",
            "http://localhost/work",
            "-u",
            "user",
            "-p",
            "pass",
            "--depth",
            "0",
        ]
    )
    assert args.command == "client"
    assert args.client_action == "propfind"
    assert args.username == "user"
    assert args.password == "pass"
    assert args.depth == 0

    # auth login
    args = parser.parse_args(["auth", "login", "-u", "user", "-p", "pass"])
    assert args.command == "auth"
    assert args.auth_action == "login"

    # store inspect
    args = parser.parse_args(["store", "inspect"])
    assert args.command == "store"
    assert args.store_action == "inspect"


@pytest.mark.asyncio
async def test_cli_auth_subcommands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test icaldav auth login, status, and logout subcommands."""
    config_file = tmp_path / "auth.json"
    with patch.object(
        AuthStore,
        "__init__",
        lambda self, config_path=config_file: setattr(self, "config_path", config_path),
    ):
        # 1. login
        code = await main_async(
            [
                "auth",
                "login",
                "--url",
                "https://caldav.example.com",
                "-u",
                "alice",
                "-p",
                "secret",
            ]
        )
        assert code == 0
        captured = capsys.readouterr()
        assert "Saved credentials profile" in captured.out

        # 2. status
        code = await main_async(["auth", "status"])
        assert code == 0
        captured = capsys.readouterr()
        assert "Saved Authentication Profiles" in captured.out
        assert "alice" in captured.out

        # 3. logout
        code = await main_async(["auth", "logout"])
        assert code == 0
        captured = capsys.readouterr()
        assert "Successfully cleared" in captured.out


@pytest.mark.asyncio
async def test_cli_client_commands_integration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test CLI client subcommands (propfind, put, get, delete) against in-process router."""
    store = MemoryStore()
    app = create_app(store)

    async with TestServer(app) as server, TestClient(server):
        base_url = str(server.make_url("/work"))

        # 1. propfind empty collection
        code = await main_async(["client", "propfind", base_url])
        assert code == 0
        captured = capsys.readouterr()
        assert "PROPFIND Response" in captured.out

        # 2. put calendar resource file
        ics_file = tmp_path / "meeting.ics"
        ics_file.write_text(
            "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:999\r\nEND:VEVENT\r\nEND:VCALENDAR",
            encoding="utf-8",
        )
        event_url = f"{base_url}/meeting.ics"
        code = await main_async(["client", "put", event_url, str(ics_file)])
        assert code == 0
        captured = capsys.readouterr()
        assert "Successfully uploaded" in captured.out

        # 3. get calendar resource
        code = await main_async(["client", "get", event_url])
        assert code == 0
        captured = capsys.readouterr()
        assert "UID:999" in captured.out

        # 4. delete calendar resource
        code = await main_async(["client", "delete", event_url])
        assert code == 0
        captured = capsys.readouterr()
        assert "Successfully deleted" in captured.out

        # 5. store inspect
        code = await main_async(["store", "inspect"])
        assert code == 0
        captured = capsys.readouterr()
        assert "Store Inspection" in captured.out


def test_cli_parser_auth_probe() -> None:
    """Test auth probe subcommand argument parsing."""
    parser = build_parser()
    args = parser.parse_args(["auth", "probe", "https://caldav.example.com"])
    assert args.command == "auth"
    assert args.auth_action == "probe"
    assert args.url == "https://caldav.example.com"


def test_cli_parser_auth_oauth() -> None:
    """Test auth oauth subcommand argument parsing."""
    parser = build_parser()
    args = parser.parse_args(
        [
            "auth",
            "oauth",
            "https://caldav.example.com",
            "--client-id",
            "test-id",
            "--client-secret",
            "test-secret",
            "--port",
            "9999",
        ]
    )
    assert args.command == "auth"
    assert args.auth_action == "oauth"
    assert args.url == "https://caldav.example.com"
    assert args.client_id == "test-id"
    assert args.client_secret == "test-secret"
    assert args.port == 9999


def test_cli_parser_auth_oauth_defaults() -> None:
    """Test auth oauth subcommand uses default port."""
    parser = build_parser()
    args = parser.parse_args(
        [
            "auth",
            "oauth",
            "https://example.com",
            "--client-id",
            "id",
            "--client-secret",
            "secret",
        ]
    )
    assert args.port == 8088
