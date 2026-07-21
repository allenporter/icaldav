"""Command-Line Interface (CLI) for icaldav.

Provides interactive developer and AI agent tooling for running the live CalDavRouter
HTTP web server, executing CalDavClient WebDAV/CalDAV operations, and inspecting
LocalStore persistence.

CLI Command Reference & Usage Examples:

1. Server Command (`serve`):
   Launches the embeddable CalDavRouter web application live over HTTP.
   $ icaldav serve [--host HOST] [--port PORT] [--store {memory}]
   Example:
     $ icaldav serve --host 127.0.0.1 --port 8080

2. Client Query Commands (`client`):
   Executes HTTP/WebDAV operations against any CalDAV server (local or remote).
   - PROPFIND (Collection Discovery & Stat):
     $ icaldav client propfind URL [--depth {0,1}]
     Example:
       $ icaldav client propfind http://127.0.0.1:8080/work --depth 1
   - GET (Fetch Calendar Object Resource):
     $ icaldav client get URL
     Example:
       $ icaldav client get http://127.0.0.1:8080/work/meeting.ics
   - PUT (Upload Calendar Object Resource File):
     $ icaldav client put URL FILE.ics
     Example:
       $ icaldav client put http://127.0.0.1:8080/work/meeting.ics sample.ics
   - DELETE (Delete Calendar Resource):
     $ icaldav client delete URL
     Example:
       $ icaldav client delete http://127.0.0.1:8080/work/meeting.ics

3. Storage Commands (`store`):
   Inspects local store collections and persistence status.
   $ icaldav store inspect

End-to-End Workflow Example:
  1. Start server in terminal 1:
     $ icaldav serve --port 8080
  2. Query collection listing in terminal 2:
     $ icaldav client propfind http://127.0.0.1:8080/work
  3. Upload an .ics file:
     $ icaldav client put http://127.0.0.1:8080/work/meeting.ics event.ics
  4. Fetch uploaded event:
     $ icaldav client get http://127.0.0.1:8080/work/meeting.ics
  5. Delete event:
     $ icaldav client delete http://127.0.0.1:8080/work/meeting.ics

RFC References:
  - RFC 4918 Section 9.1: PROPFIND Method.
  - RFC 4918 Section 9.7: DELETE Method.
  - RFC 4918 Section 9.10: OPTIONS Method.
  - RFC 4791 Section 5.2: Calendar Object Resources (GET / PUT).
"""

import argparse
import asyncio
from pathlib import Path
import sys
from typing import Sequence
from aiohttp import web

from icaldav.client.client import CalDavClient
from icaldav.server.router import create_app
from icaldav.store.memory import MemoryStore


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level ArgumentParser for the icaldav CLI.

    Returns:
        Configured ArgumentParser with subcommands for serve, client, and store.
    """
    parser = argparse.ArgumentParser(
        prog="icaldav",
        description="icaldav CLI — CalDAV server, client transport, and storage tools.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # 1. serve
    serve_parser = subparsers.add_parser(
        "serve", help="Run the embeddable CalDavRouter HTTP web server"
    )
    serve_parser.add_argument(
        "--host", default="127.0.0.1", help="Bind host IP address (default: 127.0.0.1)"
    )
    serve_parser.add_argument(
        "--port", type=int, default=8080, help="Bind port number (default: 8080)"
    )
    serve_parser.add_argument(
        "--store",
        choices=["memory"],
        default="memory",
        help="Storage backend implementation (default: memory)",
    )

    # 2. client
    client_parser = subparsers.add_parser(
        "client", help="Execute CalDavClient WebDAV and CalDAV operations"
    )
    client_subparsers = client_parser.add_subparsers(
        dest="client_action", help="Client action"
    )

    # client propfind
    pf_parser = client_subparsers.add_parser(
        "propfind", help="Execute WebDAV PROPFIND query"
    )
    pf_parser.add_argument("url", help="Target collection or resource URL")
    pf_parser.add_argument(
        "--depth", type=int, choices=[0, 1], default=1, help="Depth header (0 or 1)"
    )

    # client get
    get_parser = client_subparsers.add_parser(
        "get", help="Fetch raw .ics calendar resource"
    )
    get_parser.add_argument("url", help="Target calendar resource URL")

    # client put
    put_parser = client_subparsers.add_parser(
        "put", help="Upload raw .ics calendar resource file"
    )
    put_parser.add_argument("url", help="Target calendar resource URL")
    put_parser.add_argument("file", type=Path, help="Path to local .ics file to upload")

    # client delete
    del_parser = client_subparsers.add_parser(
        "delete", help="Delete a calendar resource"
    )
    del_parser.add_argument("url", help="Target calendar resource URL")

    # 3. store
    store_parser = subparsers.add_parser(
        "store", help="Inspect local storage persistence"
    )
    store_subparsers = store_parser.add_subparsers(
        dest="store_action", help="Store action"
    )
    store_subparsers.add_parser(
        "inspect", help="Display stored collections and resources"
    )

    return parser


def run_serve(args: argparse.Namespace) -> int:
    """Execute the serve CLI action to launch CalDavRouter server.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code integer.
    """
    store = MemoryStore()
    app = create_app(store)
    print(
        f"Starting icaldav CalDavRouter server on http://{args.host}:{args.port} (store: {args.store})..."
    )
    web.run_app(app, host=args.host, port=args.port)
    return 0


async def run_client_async(args: argparse.Namespace) -> int:
    """Async handler executing client subcommands.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code integer.
    """
    action = args.client_action
    if not action:
        print("Error: Missing client action. Use --help for usage.", file=sys.stderr)
        return 1

    async with CalDavClient() as client:
        if action == "propfind":
            items = await client.propfind(args.url, depth=args.depth)
            print(f"PROPFIND Response for {args.url} (Depth: {args.depth}):")
            for item in items:
                res_type = (
                    "Collection"
                    if item.is_collection
                    else f"Resource (etag: {item.etag})"
                )
                print(f"  - {item.href} [{res_type}]")
        elif action == "get":
            ics_text, etag = await client.get_resource(args.url)
            print(f'ETag: "{etag}"\nContent:\n{ics_text}')
        elif action == "put":
            if not args.file.exists():
                print(f"Error: File '{args.file}' does not exist.", file=sys.stderr)
                return 1
            ics_content = args.file.read_text(encoding="utf-8")
            etag = await client.put_resource(args.url, ics_content)
            print(
                f"Successfully uploaded '{args.file}' to {args.url} (ETag: \"{etag}\")"
            )
        elif action == "delete":
            await client.delete_resource(args.url)
            print(f"Successfully deleted {args.url}")
    return 0


def run_client(args: argparse.Namespace) -> int:
    """Execute client CLI actions synchronously via asyncio.run().

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code integer.
    """
    return asyncio.run(run_client_async(args))


def run_store(args: argparse.Namespace) -> int:
    """Execute store CLI actions.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code integer.
    """
    action = args.store_action
    if action == "inspect":
        print("Store Inspection: MemoryStore (transient in-memory storage active)")
    else:
        print("Error: Missing store action. Use --help for usage.", file=sys.stderr)
        return 1
    return 0


async def main_async(argv: Sequence[str] | None = None) -> int:
    """Async main entry point for the icaldav CLI executable.

    Args:
        argv: Optional sequence of command-line argument strings (defaults to sys.argv[1:]).

    Returns:
        Exit code integer.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "serve":
        return run_serve(args)
    elif args.command == "client":
        return await run_client_async(args)
    elif args.command == "store":
        return run_store(args)

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entry point for the icaldav executable.

    Args:
        argv: Optional sequence of command-line argument strings (defaults to sys.argv[1:]).

    Returns:
        Exit code integer.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "serve":
        return run_serve(args)
    elif args.command == "client":
        return run_client(args)
    elif args.command == "store":
        return run_store(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
