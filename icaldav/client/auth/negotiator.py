"""Authentication negotiation for CalDAV server discovery (RFC 7235)."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

import aiohttp
from multidict import CIMultiDictProxy

from icaldav.client.auth.models import AuthMethod, AuthScheme
from icaldav.client.auth.oauth.config import discover_oauth_config
from icaldav.xml.propfind.request import build_propfind_xml

_LOGGER = logging.getLogger(__name__)

# Known provider mapping (hostname -> OpenID issuer URL)
KNOWN_OAUTH_ISSUERS: dict[str, str] = {
    "apidata.googleusercontent.com": "https://accounts.google.com",
    "www.googleapis.com": "https://accounts.google.com",
    "outlook.office365.com": "https://login.microsoftonline.com/common/v2.0",
    "caldav.fastmail.com": "",
    "caldav.icloud.com": "",
    "p01-caldav.icloud.com": "",
    "p02-caldav.icloud.com": "",
    "p03-caldav.icloud.com": "",
}

_REALM_RE = re.compile(r'realm="([^"]*)"', re.IGNORECASE)


class AuthNegotiator:
    """Probe a CalDAV server URL to discover supported authentication methods."""

    async def probe(self, url: str) -> list[AuthMethod]:
        """Probe CalDAV URL with unauthenticated PROPFIND and return AuthMethods."""
        parsed_url = urlparse(url)
        hostname = parsed_url.hostname or ""
        body = build_propfind_xml(["resourcetype"])
        headers = {"Depth": "0", "Content-Type": "application/xml; charset=utf-8"}

        try:
            async with (
                aiohttp.ClientSession() as session,
                session.request("PROPFIND", url, data=body, headers=headers) as resp,
            ):
                if 200 <= resp.status < 300:
                    return [AuthMethod(scheme=AuthScheme.NONE)]

                if resp.status != 401:
                    return [AuthMethod(scheme=AuthScheme.UNKNOWN)]

                challenges = self._parse_challenges(resp.headers)
                if not challenges and hostname in KNOWN_OAUTH_ISSUERS:
                    challenges = [("Bearer", None)]

                if not challenges:
                    return [AuthMethod(scheme=AuthScheme.UNKNOWN)]

                methods = []
                for scheme, realm in challenges:
                    method = await self._resolve_scheme(
                        scheme, realm, hostname, parsed_url.scheme
                    )
                    methods.append(method)
                return methods
        except aiohttp.ClientError:
            _LOGGER.error("Connection error probing %s", url, exc_info=True)
            raise

    def _parse_challenges(
        self, headers: CIMultiDictProxy[str]
    ) -> list[tuple[str, str | None]]:
        """Extract (scheme, realm) pairs from WWW-Authenticate headers."""
        results: list[tuple[str, str | None]] = []
        for raw in headers.getall("WWW-Authenticate", []):
            for part in re.split(r",\s*(?=[A-Z])", raw):
                part = part.strip()
                if not part:
                    continue
                scheme = part.split(None, 1)[0]
                realm_match = _REALM_RE.search(part)
                results.append((scheme, realm_match.group(1) if realm_match else None))
        return results

    async def _resolve_scheme(
        self, scheme: str, realm: str | None, hostname: str, url_scheme: str
    ) -> AuthMethod:
        """Resolve a challenge scheme into an AuthMethod with optional OAuth config."""
        try:
            scheme_enum = AuthScheme(scheme.lower())
        except ValueError:
            scheme_enum = AuthScheme.UNKNOWN

        if scheme_enum != AuthScheme.BEARER:
            return AuthMethod(scheme=scheme_enum, realm=realm)

        issuer_url = KNOWN_OAUTH_ISSUERS.get(hostname)
        if issuer_url == "":
            return AuthMethod(scheme=AuthScheme.BEARER, realm=realm)

        if not issuer_url:
            issuer_url = f"{url_scheme}://{hostname}"

        try:
            config = await discover_oauth_config(issuer_url)
            return AuthMethod(scheme=AuthScheme.OAUTH, realm=realm, oauth_config=config)
        except Exception:
            _LOGGER.debug("OIDC discovery failed for %s", issuer_url, exc_info=True)
            return AuthMethod(scheme=AuthScheme.BEARER, realm=realm)
