# Integration Testing with Radicale

Local integration tests against a real CalDAV server ([Radicale](https://radicale.org/)) running in Docker. These are manual developer tests, not run in CI.

## Prerequisites

- Docker Desktop running
- `uv` installed (for `uv run`)

## Setup

Start Radicale (default config accepts any username/password):

```bash
docker run -d --name radicale-test -p 5232:5232 tomsquest/docker-radicale:latest
```

Create a test calendar collection:

```bash
curl -s -u testuser:testpass -X MKCALENDAR http://localhost:5232/testuser/work/
# Expected: HTTP 201
```

## Test Sequence

### 1. PROPFIND — Empty Collection

```bash
uv run icaldav client propfind http://localhost:5232/testuser/work/ -u testuser -p testpass --depth 1
```

Expected output:
```
PROPFIND Response for http://localhost:5232/testuser/work/ (Depth: 1):
  - /testuser/work/ [Collection]
```

### 2. PUT — Upload Calendar Resources

```bash
uv run icaldav client put http://localhost:5232/testuser/work/meeting.ics examples/work_meeting.ics -u testuser -p testpass
uv run icaldav client put http://localhost:5232/testuser/work/standup.ics examples/recurring_sync.ics -u testuser -p testpass
uv run icaldav client put http://localhost:5232/testuser/work/todo.ics examples/todo_task.ics -u testuser -p testpass
```

Expected: each prints `Successfully uploaded ... (ETag: "...")`.

### 3. PROPFIND — Populated Collection

```bash
uv run icaldav client propfind http://localhost:5232/testuser/work/ -u testuser -p testpass --depth 1
```

Expected: collection + 3 resources with ETags listed.

### 4. GET — Fetch Resource Content

```bash
uv run icaldav client get http://localhost:5232/testuser/work/meeting.ics -u testuser -p testpass
```

Expected: full iCalendar `BEGIN:VCALENDAR ... END:VCALENDAR` payload with ETag.

### 5. DELETE — Remove Resource

```bash
uv run icaldav client delete http://localhost:5232/testuser/work/todo.ics -u testuser -p testpass
```

Expected: `Successfully deleted ...`. Subsequent PROPFIND shows 2 resources.

### 6. Auth Store — Credential Persistence

```bash
# Save credentials
uv run icaldav auth login --url http://localhost:5232 -u testuser -p testpass

# Verify saved
uv run icaldav auth status

# Use stored credentials (no -u/-p flags)
uv run icaldav client propfind http://localhost:5232/testuser/work/ --depth 1

# Clean up
uv run icaldav auth logout
```

## Teardown

```bash
docker stop radicale-test && docker rm radicale-test
```

## Notes

- Radicale's default Docker image uses `none` auth type — it accepts any username/password. This is fine for testing our Basic Auth header generation but won't test 401 rejection flows.
- Radicale stores data inside the container at `/data/`. Data is lost when the container is removed.
- The URL path structure is `/{username}/{calendar}/` — Radicale auto-creates user directories.
