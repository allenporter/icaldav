-- SQLite schema for icaldav persistent LocalStore and PrincipalStore
-- RFC References:
--   - RFC 4918 / RFC 4791: Collections and calendar object resources.
--   - RFC 6578: WebDAV sync collection tokens and deleted tombstones.
--   - RFC 3744: WebDAV Access Control Protocol / Principal Directory.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS collections (
    path TEXT PRIMARY KEY,
    sync_token_counter INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS resources (
    path TEXT PRIMARY KEY,
    collection_path TEXT NOT NULL,
    etag TEXT NOT NULL,
    ics_data TEXT NOT NULL,
    uid TEXT,
    token_id INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(collection_path) REFERENCES collections(path) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tombstones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    collection_path TEXT NOT NULL,
    token_id INTEGER NOT NULL,
    deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(collection_path) REFERENCES collections(path) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS principals (
    user_id TEXT PRIMARY KEY,
    principal_path TEXT NOT NULL,
    calendar_home_path TEXT NOT NULL,
    email TEXT NOT NULL,
    display_name TEXT,
    is_default INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_resources_collection ON resources(collection_path);
CREATE INDEX IF NOT EXISTS idx_tombstones_collection ON tombstones(collection_path);
CREATE INDEX IF NOT EXISTS idx_principals_email ON principals(email);
