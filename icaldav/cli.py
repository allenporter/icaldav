"""Command-Line Interface (CLI) for icaldav.

Provides interactive developer and AI agent tooling for running the live CalDavRouter
HTTP web server, executing CalDavClient WebDAV/CalDAV operations, managing authentication
credentials, and inspecting LocalStore persistence.

CLI Command Reference & Usage Examples:

1. Authentication Commands (`auth`):
   Manages stored credentials in ~/.config/icaldav/auth.json (0o600 permissions).
   - Save credentials:
     $ icaldav auth login --url https://caldav.example.com -u myuser -p mypass
     $ icaldav auth login --url https://caldav.example.com --token mytoken
   - Display auth status:
     $ icaldav auth status
   - Clear credentials:
     $ icaldav auth logout

2. Server Command (`serve`):
   Launches the embeddable CalDavRouter web application live over HTTP.
   $ icaldav serve [--host HOST] [--port PORT] [--store {memory}]
   Example:
     $ icaldav serve --host 127.0.0.1 --port 8080

3. Client Query Commands (`client`):
   Executes HTTP/WebDAV operations against any CalDAV server (local or remote).
   - PROPFIND (Collection Discovery & Stat):
     $ icaldav client propfind URL [-u USER] [-p PASS] [--token TOKEN] [--depth {0,1}]
     Example:
       $ icaldav client propfind http://127.0.0.1:8080/work --depth 1
   - GET (Fetch Calendar Object Resource):
     $ icaldav client get URL [-u USER] [-p PASS] [--token TOKEN]
   - PUT (Upload Calendar Object Resource File):
     $ icaldav client put URL FILE.ics [-u USER] [-p PASS] [--token TOKEN]
   - DELETE (Delete Calendar Resource):
     $ icaldav client delete URL [-u USER] [-p PASS] [--token TOKEN]

4. Storage Commands (`store`):
   Inspects local store collections and persistence status.
   $ icaldav store inspect

RFC References:
  - RFC 4918 Section 9.1: PROPFIND Method.
  - RFC 4918 Section 9.7: DELETE Method.
  - RFC 4918 Section 9.10: OPTIONS Method.
  - RFC 4791 Section 5.2: Calendar Object Resources (GET / PUT).
  - RFC 7617: HTTP Basic Authentication.
  - RFC 6750: OAuth 2.0 Bearer Tokens.
"""

import argparse
import asyncio
import os
from pathlib import Path
import sys
from typing import Sequence
from aiohttp import web

import webbrowser

from icaldav.client.auth import AuthProfile, AuthStore
from icaldav.client.client import CalDavClient
from icaldav.client.exceptions import CalDavAuthError
from icaldav.client.negotiator import AuthNegotiator
from icaldav.client.oauth import OAuthConfig, OAuthSession
from icaldav.server.router import create_app
from icaldav.store.memory import MemoryStore


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level ArgumentParser for the icaldav CLI.

    Returns:
        Configured ArgumentParser with subcommands for auth, serve, client, and store.
    """
    parser = argparse.ArgumentParser(
        prog="icaldav",
        description="icaldav CLI — CalDAV server, client transport, auth, and storage tools.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # 1. auth
    auth_parser = subparsers.add_parser(
        "auth", help="Manage CalDAV server authentication credentials"
    )
    auth_subparsers = auth_parser.add_subparsers(dest="auth_action", help="Auth action")

    login_parser = auth_subparsers.add_parser(
        "login", help="Save server credentials to ~/.config/icaldav/auth.json"
    )
    login_parser.add_argument(
        "--url", default="default", help="Server base URL or host"
    )
    login_parser.add_argument("-u", "--username", help="HTTP Basic Auth username")
    login_parser.add_argument("-p", "--password", help="HTTP Basic Auth password")
    login_parser.add_argument("--token", help="OAuth 2.0 Bearer token")

    auth_subparsers.add_parser("status", help="Display saved authentication profiles")
    auth_subparsers.add_parser("logout", help="Clear all stored credentials")

    probe_parser = auth_subparsers.add_parser(
        "probe",
        help="Probe a CalDAV server URL and discover supported authentication methods",
    )
    probe_parser.add_argument("url", help="CalDAV server URL to probe")

    oauth_parser = auth_subparsers.add_parser(
        "oauth", help="Authenticate with a CalDAV server using OAuth 2.0 browser flow"
    )
    oauth_parser.add_argument("url", help="CalDAV server URL to authenticate against")
    oauth_parser.add_argument("--client-id", required=True, help="OAuth 2.0 client ID")
    oauth_parser.add_argument(
        "--client-secret", required=True, help="OAuth 2.0 client secret"
    )
    oauth_parser.add_argument(
        "--port", type=int, default=8088, help="Local callback port (default: 8088)"
    )

    # 2. serve
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

    # 3. client
    client_parser = subparsers.add_parser(
        "client", help="Execute CalDavClient WebDAV and CalDAV operations"
    )
    client_subparsers = client_parser.add_subparsers(
        dest="client_action", help="Client action"
    )

    # Helper function to add credential flags to client subparsers
    def add_auth_flags(p: argparse.ArgumentParser) -> None:
        p.add_argument("-u", "--username", help="HTTP Basic Auth username")
        p.add_argument("-p", "--password", help="HTTP Basic Auth password")
        p.add_argument("--token", help="OAuth 2.0 Bearer token")

    # client propfind
    pf_parser = client_subparsers.add_parser(
        "propfind", help="Execute WebDAV PROPFIND query"
    )
    pf_parser.add_argument("url", help="Target collection or resource URL")
    pf_parser.add_argument(
        "--depth", type=int, choices=[0, 1], default=1, help="Depth header (0 or 1)"
    )
    add_auth_flags(pf_parser)

    # client get
    get_parser = client_subparsers.add_parser(
        "get", help="Fetch raw .ics calendar resource"
    )
    get_parser.add_argument("url", help="Target calendar resource URL")
    add_auth_flags(get_parser)

    # client put
    put_parser = client_subparsers.add_parser(
        "put", help="Upload raw .ics calendar resource file"
    )
    put_parser.add_argument("url", help="Target calendar resource URL")
    put_parser.add_argument("file", type=Path, help="Path to local .ics file to upload")
    add_auth_flags(put_parser)

    # client delete
    del_parser = client_subparsers.add_parser(
        "delete", help="Delete a calendar resource"
    )
    del_parser.add_argument("url", help="Target calendar resource URL")
    add_auth_flags(del_parser)

    # client query (calendar-query REPORT)
    query_parser = client_subparsers.add_parser(
        "query", help="Execute CalDAV calendar-query REPORT"
    )
    query_parser.add_argument("url", help="Target collection URL")
    query_parser.add_argument(
        "--component",
        default="VEVENT",
        help="Component type filter (default: VEVENT)",
    )
    query_parser.add_argument("--start", help="UTC start time (e.g. 20260701T000000Z)")
    query_parser.add_argument("--end", help="UTC end time (e.g. 20260801T000000Z)")
    add_auth_flags(query_parser)

    # client multiget (calendar-multiget REPORT)
    multiget_parser = client_subparsers.add_parser(
        "multiget", help="Execute CalDAV calendar-multiget REPORT"
    )
    multiget_parser.add_argument("url", help="Target collection URL")
    multiget_parser.add_argument(
        "hrefs", nargs="+", help="Resource href paths to fetch"
    )
    add_auth_flags(multiget_parser)

    # 4. store
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


async def run_auth_async(args: argparse.Namespace) -> int:
    """Async handler executing auth CLI subcommands.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code integer.
    """
    action = args.auth_action
    auth_store = AuthStore()

    if action == "login":
        if not (args.token or (args.username and args.password)):
            print(
                "Error: Specify either --username and --password OR --token.",
                file=sys.stderr,
            )
            return 1
        profile = AuthProfile(
            server_url=args.url,
            username=args.username,
            password=args.password,
            token=args.token,
        )
        saved = await auth_store.save_profile(profile)
        print(
            f"Saved credentials profile for '{saved.server_url}' ({saved.auth_type} auth)."
        )
    elif action == "status":
        profiles = await auth_store.load_profiles()
        if not profiles:
            print("No saved authentication profiles found.")
        else:
            print("Saved Authentication Profiles (~/.config/icaldav/auth.json):")
            for host, p in profiles.items():
                ident = p.username if p.username else "Bearer Token"
                print(f"  - [{host}] {p.server_url} ({p.auth_type}: {ident})")
    elif action == "logout":
        if await auth_store.clear_credentials():
            print("Successfully cleared all stored credentials.")
        else:
            print("No stored credentials found to clear.")
    elif action == "probe":
        negotiator = AuthNegotiator()
        print(f"Probing {args.url} ...")
        try:
            methods = await negotiator.probe(args.url)
            print(f"Discovered {len(methods)} authentication method(s):")
            for method in methods:
                if method.oauth_config:
                    print(f"  - {method.scheme} (realm: {method.realm or 'N/A'})")
                    print(f"    Auth URI:  {method.oauth_config.auth_uri}")
                    print(f"    Token URI: {method.oauth_config.token_uri}")
                else:
                    print(f"  - {method.scheme} (realm: {method.realm or 'N/A'})")
        except Exception as err:
            print(f"Error probing {args.url}: {err}", file=sys.stderr)
            return 1
    elif action == "oauth":
        # 1. Probe to discover OAuth config
        negotiator = AuthNegotiator()
        print(f"Probing {args.url} for OAuth endpoints...")
        try:
            methods = await negotiator.probe(args.url)
        except Exception as err:
            print(f"Error probing {args.url}: {err}", file=sys.stderr)
            return 1

        # Find an OAuth method
        oauth_method = next(
            (m for m in methods if m.scheme == "oauth" and m.oauth_config), None
        )
        if not oauth_method or not oauth_method.oauth_config:
            print(
                "Error: No OAuth endpoint discovered for this server.", file=sys.stderr
            )
            print(
                "Discovered methods: " + ", ".join(m.scheme for m in methods),
                file=sys.stderr,
            )
            return 1

        # 2. Configure OAuth with discovered endpoints + user's credentials
        config = OAuthConfig(
            client_id=args.client_id,
            client_secret=args.client_secret,
            auth_uri=oauth_method.oauth_config.auth_uri,
            token_uri=oauth_method.oauth_config.token_uri,
            redirect_uri=f"http://localhost:{args.port}",
            scopes=oauth_method.oauth_config.scopes
            or ["https://www.googleapis.com/auth/calendar"],
        )

        # 3. Build auth URL with PKCE and open browser
        auth_url, code_verifier = OAuthSession.authorize_url(config)
        print("\nOpening browser for authorization...")
        print(f"If the browser doesn't open, visit:\n  {auth_url}\n")
        webbrowser.open(auth_url)

        # 4. Receive authorization code via temporary callback listener
        print(f"Waiting for OAuth callback on http://localhost:{args.port} ...")
        try:
            code = await OAuthSession.fetch_code_from_callback(port=args.port)
        except asyncio.TimeoutError:
            print("Error: OAuth callback timed out after 5 minutes.", file=sys.stderr)
            return 1
        except Exception as err:
            print(f"Error receiving authorization code: {err}", file=sys.stderr)
            return 1

        # 5. Exchange code for tokens
        print("Exchanging authorization code for tokens...")
        try:
            token = await OAuthSession.exchange_code(config, code, code_verifier)
        except Exception as err:
            print(f"Error exchanging code: {err}", file=sys.stderr)
            return 1

        # 6. Save to auth store
        profile = AuthProfile(
            server_url=args.url,
            token=token.access_token,
            client_id=args.client_id,
            client_secret=args.client_secret,
            refresh_token=token.refresh_token,
            token_uri=config.token_uri,
            token_expires_at=token.expires_at,
        )
        auth_store = AuthStore()
        await auth_store.save_profile(profile)
        print(
            f"\nSuccessfully authenticated! OAuth credentials saved for '{args.url}'."
        )
        if token.refresh_token:
            print("Refresh token stored \u2014 access token will auto-refresh.")
    else:
        print("Error: Missing auth action. Use --help for usage.", file=sys.stderr)
        return 1
    return 0


def run_auth(args: argparse.Namespace) -> int:
    """Execute auth CLI subcommands synchronously via asyncio.run().

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code integer.
    """
    return asyncio.run(run_auth_async(args))


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
    """Async handler executing client subcommands with credential resolution.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Exit code integer.
    """
    action = args.client_action
    if not action:
        print("Error: Missing client action. Use --help for usage.", file=sys.stderr)
        return 1

    # Resolve credentials: CLI flags > env vars > AuthStore fallback
    username = getattr(args, "username", None) or os.environ.get("ICALDAV_USERNAME")
    password = getattr(args, "password", None) or os.environ.get("ICALDAV_PASSWORD")
    token = getattr(args, "token", None) or os.environ.get("ICALDAV_TOKEN")

    if not (token or (username and password)):
        auth_store = AuthStore()
        saved_profile = await auth_store.get_profile(args.url)
        if saved_profile:
            username = username or saved_profile.username
            password = password or saved_profile.password
            token = token or saved_profile.token

    try:
        async with CalDavClient(
            username=username, password=password, token=token
        ) as client:
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
            elif action == "query":
                resources = await client.calendar_query(
                    args.url,
                    component=args.component,
                    time_start=args.start,
                    time_end=args.end,
                )
                print(
                    f"calendar-query REPORT for {args.url} "
                    f"(component={args.component}):"
                )
                if not resources:
                    print("  (no matching resources)")
                for res in resources:
                    print(f"  - {res.href} [etag: {res.etag}]")
                    if res.ics_data:
                        # Print first SUMMARY line if available
                        for line in res.ics_data.splitlines():
                            if line.startswith("SUMMARY:"):
                                print(f"    {line}")
                                break
            elif action == "multiget":
                resources = await client.calendar_multiget(args.url, hrefs=args.hrefs)
                print(f"calendar-multiget REPORT for {args.url}:")
                for res in resources:
                    print(f"  - {res.href} [etag: {res.etag}]")
                    if res.ics_data:
                        print(f"    Content:\n{res.ics_data}")
        return 0
    except CalDavAuthError as err:
        print(f"Authentication Error (HTTP {err.status}): {err}", file=sys.stderr)
        if err.challenges:
            print(
                f"Server WWW-Authenticate Challenges: {err.challenges}", file=sys.stderr
            )
        print(
            "Use 'icaldav auth login' or supply -u/--username, -p/--password, or --token.",
            file=sys.stderr,
        )
        return 1


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

    if args.command == "auth":
        return await run_auth_async(args)
    elif args.command == "serve":
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

    if args.command == "auth":
        return run_auth(args)
    elif args.command == "serve":
        return run_serve(args)
    elif args.command == "client":
        return run_client(args)
    elif args.command == "store":
        return run_store(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
