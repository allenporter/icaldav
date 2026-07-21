# CalDAV Server Reconnaissance & Compatibility Matrix

This document records real-world protocol behavior, authentication mechanics, probing heuristics, and implementation quirks discovered across commercial and self-hosted CalDAV providers.

---

## 1. Reconnaissance & Probing Architecture

`icaldav` uses an unauthenticated **`PROPFIND` probe** (`Depth: 0`) to discover a server's supported authentication methods and discovery endpoints.

```
                    +-----------------------------+
                    |  PROPFIND <URL> (Depth: 0)  |
                    +-----------------------------+
                                   |
         +-------------------------+-------------------------+
         | HTTP 2xx                                          | HTTP 401
         v                                                   v
+------------------+                              +-----------------------+
|  Auth: 'none'    |                              | WWW-Authenticate      |
|  (Public Server) |                              | Header Challenge(s)   |
+------------------+                              +-----------------------+
                                                             |
                        +------------------------------------+------------------------------------+
                        | Scheme: 'Basic'                                                         | Scheme: 'Bearer'
                        v                                                                         v
             +--------------------+                                                    +--------------------+
             |   Auth: 'basic'    |                                                    | Host in Known      |
             |   (Realm parsed)   |                                                    | Issuer Mapping?    |
             +--------------------+                                                    +--------------------+
                                                                                                  |
                                                                        +-------------------------+-------------------------+
                                                                        | Host Mapped (e.g. Google)                         | Unknown Host
                                                                        v                                                   v
                                                            +-----------------------+                           +-----------------------+
                                                            | OpenID Connect        |                           | Origin Discovery      |
                                                            | Discovery (.well-known|                           | ({origin}/.well-known)|
                                                            +-----------------------+                           +-----------------------+
                                                                        |                                                   |
                                                                        +-------------------------+-------------------------+
                                                                                                  |
                                                                              +-------------------+-------------------+
                                                                              | Discovery Success                     | Discovery Failed
                                                                              v                                       v
                                                                   +---------------------+                 +--------------------+
                                                                   |    Auth: 'oauth'    |                 |   Auth: 'bearer'   |
                                                                   | (Auth & Token URIs) |                 |   (Static Token)   |
                                                                   +---------------------+                 +--------------------+
```

---

## 2. Real-World Provider Matrix

Below is the verified behavioral matrix compiled from live protocol testing against major providers:

| Provider | CalDAV Base URL | Supported Auth | 401 `WWW-Authenticate` Header | Discovery Mechanism & Quirks |
| :--- | :--- | :--- | :--- | :--- |
| **Google Calendar** | `https://apidata.googleusercontent.com/caldav/v2/` | `oauth` | *(Missing header on 401)* | Mapped to `https://accounts.google.com`. Discovers `auth_uri` and `token_uri` via OpenID Connect discovery. |
| **Apple iCloud** | `https://caldav.icloud.com/` | `basic` | `Basic realm="MMCalDav"`, `X-MobileMe-AuthToken realm="MMCalDav"` | Uses App-Specific Passwords generated in Apple ID portal. |
| **Fastmail** | `https://caldav.fastmail.com/dav/` | `basic`, `bearer` | `Basic realm="caldav.fastmail.com", Bearer` | Root path `/` returns `404`; collection endpoint requires `/dav/` suffix. Combines Basic + Bearer in single header. |
| **Mailbox.org** | `https://dav.mailbox.org/caldav/` | `basic` | `Basic realm="OX WebDAV", encoding="UTF-8"` | Powered by Open-Xchange (OX WebDAV). |
| **Microsoft 365** | `https://outlook.office365.com/` | `oauth` | `Bearer authorization_uri="https://login.windows.net/..."` | Mapped to `https://login.microsoftonline.com/common/v2.0`. |
| **Nextcloud** | `https://<domain>/remote.php/dav/` | `basic`, `bearer` | `Basic realm="Nextcloud"`, `Bearer` | Supports RFC 6578 `sync-collection` and WebDAV app passwords. |
| **Radicale** | `http://<host>:<port>/` | `basic`, `none` | `Basic realm="Radicale"` | Simple flat-file server. Default instance may operate unauthenticated. |

---

## 3. Server Quirks & Edge Case Protocols

### Quirk A: 401 Unauthorized Missing `WWW-Authenticate` Header
- **Affected Server:** Google CalDAV (`apidata.googleusercontent.com`).
- **Behavior:** Returns `HTTP 401 Unauthorized` with an XML error payload (`application/vnd.google.gdata.error+xml`) but **omits** the standard `WWW-Authenticate` HTTP header.
- **Handling in `icaldav`:** `AuthNegotiator` inspects the URL's hostname. If the host is in `KNOWN_OAUTH_ISSUERS`, it proceeds with OpenID Connect discovery for the mapped issuer (`https://accounts.google.com`) despite the missing challenge header.

### Quirk B: Multi-Challenge Header Formatting
- **Affected Server:** Fastmail (`caldav.fastmail.com`).
- **Behavior:** Sends multiple challenge schemes inside a single `WWW-Authenticate` header line (e.g. `WWW-Authenticate: Basic realm="caldav.fastmail.com", Bearer`).
- **Handling in `icaldav`:** `AuthNegotiator._parse_challenges()` uses regex splitting on unquoted commas (`,\s*(?=[A-Z])`) to extract all schemes independently.

### Quirk C: Root URL vs Collection Path
- **Affected Server:** Fastmail, Nextcloud.
- **Behavior:** Sending a `PROPFIND` request to `https://caldav.fastmail.com/` returns `HTTP 404 Not Found`. The CalDAV endpoint requires the `/dav/` path prefix.
- **Handling in `icaldav`:** `icaldav auth probe` requires specifying the target CalDAV endpoint path. RFC 6764 `/.well-known/caldav` redirection resolves base hostnames to valid CalDAV root paths.

---

## 4. How to Perform Recon via CLI

Inspect any CalDAV server's supported authentication methods and endpoints:

```bash
icaldav auth probe <URL>
```

### Examples

#### Google CalDAV:
```bash
$ icaldav auth probe https://apidata.googleusercontent.com/caldav/v2/
Probing https://apidata.googleusercontent.com/caldav/v2/ ...
Discovered 1 authentication method(s):
  - oauth (realm: N/A)
    Auth URI:  https://accounts.google.com/o/oauth2/v2/auth
    Token URI: https://oauth2.googleapis.com/token
```

#### Apple iCloud:
```bash
$ icaldav auth probe https://caldav.icloud.com/
Probing https://caldav.icloud.com/ ...
Discovered 2 authentication method(s):
  - basic (realm: MMCalDav)
  - x-mobileme-authtoken (realm: MMCalDav)
```

#### Fastmail:
```bash
$ icaldav auth probe https://caldav.fastmail.com/dav/
Probing https://caldav.fastmail.com/dav/ ...
Discovered 2 authentication method(s):
  - basic (realm: caldav.fastmail.com)
  - bearer (realm: N/A)
```
