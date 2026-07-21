"""Unit tests for the icaldav CLI module."""

from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from icaldav.cli import build_parser, main, main_async
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


def test_cli_parser_subcommands() -> None:
    """Test argument parsing for all subcommands."""
    parser = build_parser()

    # serve
    args = parser.parse_args(["serve", "--port", "9090"])
    assert args.command == "serve"
    assert args.port == 9090

    # client propfind
    args = parser.parse_args(
        ["client", "propfind", "http://localhost/work", "--depth", "0"]
    )
    assert args.command == "client"
    assert args.client_action == "propfind"
    assert args.depth == 0

    # store inspect
    args = parser.parse_args(["store", "inspect"])
    assert args.command == "store"
    assert args.store_action == "inspect"


@pytest.mark.asyncio
async def test_cli_client_commands_integration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test CLI client subcommands (propfind, put, get, delete) against in-process router."""
    store = MemoryStore()
    app = create_app(store)

    async with TestServer(app) as server:
        async with TestClient(server):
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
