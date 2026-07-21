"""Authentication negotiation for CalDAV server discovery.

Probes a CalDAV server URL with an unauthenticated PROPFIND request and
inspects the HTTP response to determine which authentication methods are
supported.  The negotiator parses ``WWW-Authenticate`` challenge headers
according to RFC 7235 and, when a Bearer scheme is advertised, attempts
OpenID Connect discovery to resolve full OAuth configuration.

RFC References:
  - RFC 7235 Section 4.1: WWW-Authenticate Challenge Header Field.
  - RFC 7617: The 'Basic' HTTP Authentication Scheme.
  - RFC 6750 Section 3: The OAuth 2.0 Bearer Token Usage — Error Codes.
  - RFC 8414: OAuth 2.0 Authorization Server Metadata (OpenID Discovery).
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from urllib.parse import urlparse

import aiohttp

from icaldav.client.oauth import OAuthConfig, discover_oauth_config
from icaldav.xml.propfind.request import build_propfind_xml

from multidict import CIMultiDictProxy

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known provider mapping
# ---------------------------------------------------------------------------
# Maps CalDAV hostnames to OpenID Connect issuer URLs.  An empty string
# indicates a provider that is known to support only Basic authentication
# (no OAuth/OIDC endpoint).

KNOWN_OAUTH_ISSUERS: dict[str, str] = {
    "apidata.googleusercontent.com": "https://accounts.google.com",
    "www.googleapis.com": "https://accounts.google.com",
    "outlook.office365.com": "https://login.microsoftonline.com/common/v2.0",
    "caldav.fastmail.com": "",  # Basic auth only
    "caldav.icloud.com": "",  # Basic auth only
    "p01-caldav.icloud.com": "",  # Basic auth only
    "p02-caldav.icloud.com": "",  # Basic auth only
    "p03-caldav.icloud.com": "",  # Basic auth only
}

# Regex to extract ``realm="…"`` from a WWW-Authenticate challenge string.
_REALM_RE = re.compile(r'realm="([^"]*)"', re.IGNORECASE)


# ---------------------------------------------------------------------------
# AuthMethod dataclass
# ---------------------------------------------------------------------------


@dataclass
class AuthMethod:
    """Describes a single authentication method advertised by a server.

    Attributes:
        scheme: Lowercase authentication scheme name.  One of ``'basic'``,
            ``'bearer'``, ``'oauth'``, ``'none'``, ``'digest'``, or
            ``'unknown'``.
        realm: Optional protection-space realm string extracted from the
            ``WWW-Authenticate`` challenge (RFC 7235 Section 2.2).
        oauth_config: Resolved :class:`OAuthConfig` when the scheme is
            ``'oauth'`` (i.e. OpenID Connect discovery succeeded).
    """

    scheme: str
    realm: str | None = None
    oauth_config: OAuthConfig | None = None


# ---------------------------------------------------------------------------
# AuthNegotiator
# ---------------------------------------------------------------------------


class AuthNegotiator:
    """Probe a CalDAV server to discover supported authentication methods.

    Usage::

        negotiator = AuthNegotiator()
        methods = await negotiator.probe("https://caldav.example.com/dav/")
        for m in methods:
            print(m.scheme, m.realm)

    RFC Reference:
        - RFC 7235 Section 4.1: The server MUST include at least one
          ``WWW-Authenticate`` header field in 401 responses.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def probe(self, url: str) -> list[AuthMethod]:
        """Send an unauthenticated PROPFIND and determine auth methods.

        Workflow:
          1. Issue an HTTP PROPFIND with ``Depth: 0`` and no credentials.
          2. If the server responds with a 2xx status the resource is
             publicly accessible → ``[AuthMethod(scheme='none')]``.
          3. On a 401 response, parse each ``WWW-Authenticate`` challenge
             header and build a list of :class:`AuthMethod` objects.
          4. For Bearer challenges the negotiator checks
             :data:`KNOWN_OAUTH_ISSUERS` and, when a non-empty issuer URL
             is found, performs OpenID Connect discovery to populate
             :attr:`AuthMethod.oauth_config`.

        Args:
            url: Fully-qualified CalDAV resource URL to probe.

        Returns:
            List of discovered :class:`AuthMethod` objects.  At least one
            entry is always returned.

        Raises:
            aiohttp.ClientError: Re-raised only when the connection cannot
                be established at all (DNS failure, TLS error, etc.) after
                logging the error.
        """
        body = build_propfind_xml(["resourcetype"])

        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    "PROPFIND",
                    url,
                    data=body,
                    headers={
                        "Depth": "0",
                        "Content-Type": "application/xml; charset=utf-8",
                    },
                ) as resp:
                    status = resp.status

                    # 2xx — no authentication required
                    if 200 <= status < 300:
                        _LOGGER.debug("Server %s allows unauthenticated access", url)
                        return [AuthMethod(scheme="none")]

                    # 401 — parse WWW-Authenticate challenges
                    if status == 401:
                        challenges = self._parse_challenges(resp.headers)
                        if not challenges:
                            _LOGGER.debug(
                                "401 from %s but no WWW-Authenticate header", url
                            )
                            return [AuthMethod(scheme="unknown")]

                        hostname = urlparse(url).hostname or ""
                        methods: list[AuthMethod] = []
                        for scheme, realm in challenges:
                            method = await self._resolve_challenge(
                                scheme, realm, hostname, url
                            )
                            methods.append(method)
                        return methods

                    # Any other status (403, 5xx, …)
                    _LOGGER.debug(
                        "Unexpected status %d from %s during probe", status, url
                    )
                    return [AuthMethod(scheme="unknown")]

        except aiohttp.ClientError:
            _LOGGER.error("Connection error probing %s", url, exc_info=True)
            raise

    # ------------------------------------------------------------------
    # Challenge parsing
    # ------------------------------------------------------------------

    def _parse_challenges(
        self, headers: CIMultiDictProxy[str]
    ) -> list[tuple[str, str | None]]:
        """Extract ``(scheme, realm)`` pairs from ``WWW-Authenticate`` headers.

        A single ``WWW-Authenticate`` header may contain multiple challenges
        separated by commas.  Each challenge starts with a scheme token
        (RFC 7235 Section 2.1).

        Args:
            headers: Response headers (case-insensitive multidict).

        Returns:
            List of ``(scheme_name, realm_or_none)`` tuples.  Scheme names
            are returned in their original casing; normalisation to
            lowercase happens in :meth:`_resolve_challenge`.
        """
        results: list[tuple[str, str | None]] = []
        raw_values = headers.getall("WWW-Authenticate", [])
        for raw in raw_values:
            # Split on commas that are *not* inside quoted strings.
            # A simplified heuristic: split on ", " followed by a token
            # that looks like a scheme name (uppercase letter start).
            parts = re.split(r",\s*(?=[A-Z])", raw)
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                tokens = part.split(None, 1)
                scheme = tokens[0]
                realm_match = _REALM_RE.search(part)
                realm = realm_match.group(1) if realm_match else None
                results.append((scheme, realm))
        return results

    # ------------------------------------------------------------------
    # Challenge resolution
    # ------------------------------------------------------------------

    async def _resolve_challenge(
        self,
        scheme: str,
        realm: str | None,
        hostname: str,
        url: str,
    ) -> AuthMethod:
        """Resolve a single parsed challenge into an :class:`AuthMethod`.

        For ``Basic`` and ``Digest`` challenges the mapping is
        straightforward.  For ``Bearer`` challenges the method attempts
        OpenID Connect discovery using the :data:`KNOWN_OAUTH_ISSUERS`
        table or falling back to the server origin.

        Args:
            scheme: Raw scheme name from the challenge (e.g. ``'Bearer'``).
            realm: Optional realm string extracted from the challenge.
            hostname: Hostname of the probed URL.
            url: Original probe URL (used to derive the server origin for
                fallback discovery).

        Returns:
            Resolved :class:`AuthMethod`.
        """
        scheme_lower = scheme.lower()

        if scheme_lower == "basic":
            return AuthMethod(scheme="basic", realm=realm)

        if scheme_lower == "bearer":
            return await self._resolve_bearer(realm, hostname, url)

        # Digest, NTLM, Negotiate, etc.
        return AuthMethod(scheme=scheme_lower, realm=realm)

    async def _resolve_bearer(
        self,
        realm: str | None,
        hostname: str,
        url: str,
    ) -> AuthMethod:
        """Attempt OpenID Connect discovery for a Bearer challenge.

        Resolution order:
          1. If *hostname* is in :data:`KNOWN_OAUTH_ISSUERS` and the
             mapped issuer URL is **non-empty**, run OIDC discovery
             against that issuer.
          2. If the mapped issuer URL is an **empty string**, the provider
             is known to use only Basic auth → return ``scheme='bearer'``
             without discovery.
          3. If *hostname* is **not** in the mapping, try OIDC discovery
             on the server's own origin (``https://<hostname>``).
          4. If discovery fails at any point, fall back to a plain
             ``scheme='bearer'`` result.

        Args:
            realm: Optional realm string from the challenge.
            hostname: Hostname of the CalDAV server.
            url: Original probe URL.

        Returns:
            :class:`AuthMethod` with ``scheme='oauth'`` on successful
            discovery, or ``scheme='bearer'`` otherwise.
        """
        if hostname in KNOWN_OAUTH_ISSUERS:
            issuer_url = KNOWN_OAUTH_ISSUERS[hostname]
            if not issuer_url:
                # Known non-OAuth provider (e.g. iCloud, Fastmail).
                _LOGGER.debug(
                    "Host %s is a known non-OAuth provider; skipping discovery",
                    hostname,
                )
                return AuthMethod(scheme="bearer", realm=realm)

            config = await self._try_discover(issuer_url)
            if config is not None:
                return AuthMethod(scheme="oauth", realm=realm, oauth_config=config)
            return AuthMethod(scheme="bearer", realm=realm)

        # Unknown host — attempt discovery on the server origin.
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.hostname}"
        config = await self._try_discover(origin)
        if config is not None:
            return AuthMethod(scheme="oauth", realm=realm, oauth_config=config)
        return AuthMethod(scheme="bearer", realm=realm)

    @staticmethod
    async def _try_discover(issuer_url: str) -> OAuthConfig | None:
        """Run OpenID Connect discovery, returning ``None`` on failure.

        Args:
            issuer_url: Base issuer URL for OIDC discovery.

        Returns:
            :class:`OAuthConfig` on success, or ``None`` if discovery
            fails for any reason (network error, invalid metadata, etc.).
        """
        try:
            return await discover_oauth_config(issuer_url)
        except Exception:
            _LOGGER.debug(
                "OpenID Connect discovery failed for %s",
                issuer_url,
                exc_info=True,
            )
            return None
