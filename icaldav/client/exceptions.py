"""Client exception classes for icaldav.

RFC References:
  - RFC 7235 Section 4.1: WWW-Authenticate Challenge Header Field.
  - RFC 7617: The 'Basic' HTTP Authentication Scheme.
  - RFC 6750: The OAuth 2.0 Authorization Framework: Bearer Token Usage.
"""


class CalDavError(Exception):
    """Base exception class for all icaldav client errors."""


class CalDavAuthError(CalDavError):
    """Exception raised when a CalDAV server returns 401 Unauthorized or 403 Forbidden.

    RFC Reference:
        - RFC 7235 Section 4.1: WWW-Authenticate Header Field.
    """

    def __init__(
        self,
        url: str,
        status: int,
        challenges: list[str] | None = None,
    ) -> None:
        """Initialize CalDavAuthError with request URL, HTTP status code, and parsed challenges.

        Args:
            url: Target URL that returned the authentication error.
            status: HTTP status code (401 or 403).
            challenges: Optional list of raw WWW-Authenticate header challenge strings.
        """
        self.url = url
        self.status = status
        self.challenges = challenges or []

        schemes = self.parse_schemes()
        scheme_str = ", ".join(schemes) if schemes else "Unspecified"
        super().__init__(
            f"Authentication failed for {url} (HTTP {status}). Supported schemes: {scheme_str}"
        )

    def parse_schemes(self) -> list[str]:
        """Extract authentication scheme names (e.g. ['Basic', 'Bearer', 'Digest']) from challenges.

        Returns:
            List of scheme name strings in uppercase/titlecase.
        """
        schemes: list[str] = []
        for challenge in self.challenges:
            parts = challenge.strip().split(maxsplit=1)
            if parts:
                scheme = parts[0].title()
                if scheme not in schemes:
                    schemes.append(scheme)
        return schemes
