---
name: icaldav_development
description: Operational guide and CLI tool reference for launching the CalDavRouter server, running CalDavClient queries, and testing synchronization.
---

# icaldav Development & Testing Skill

This skill guides AI agents and developers on how to interactively serve, query, and test `icaldav` CalDAV server and client functionality.

## Core Commands

| Command | Purpose / Usage |
| :--- | :--- |
| `icaldav serve [--port 8080]` | Launches the live `CalDavRouter` HTTP web server. |
| `icaldav client propfind <URL> [--depth 0|1]` | Executes WebDAV `PROPFIND` to discover collection resources and ETags. |
| `icaldav client get <URL>` | Fetches raw `.ics` calendar content and ETag from a server resource. |
| `icaldav client put <URL> <file.ics>` | Uploads a local `.ics` file payload to a server resource path. |
| `icaldav client delete <URL>` | Deletes a calendar resource URL. |
| `icaldav store inspect` | Inspects local store persistence and collection status. |

---

## Example Test Data

Use ready-to-use `.ics` files located in `examples/`:
- `examples/work_meeting.ics`: Single work meeting event (`VEVENT`).
- `examples/recurring_sync.ics`: Weekly recurring standup meeting (`VEVENT` with `RRULE`).
- `examples/todo_task.ics`: Action item to-do task (`VTODO`).

---

## Agent Live Verification Workflow

When developing or verifying new CalDAV capabilities, follow this sequence:

1. **Start Server as Background Task**:
   Launch the server on a test port (e.g. `8888`):
   ```bash
   icaldav serve --port 8888
   ```

2. **Query Collection Listing**:
   ```bash
   icaldav client propfind http://127.0.0.1:8888/work
   ```

3. **Upload Sample Calendar Resource (.ics)**:
   Upload an example payload from `examples/`:
   ```bash
   icaldav client put http://127.0.0.1:8888/work/meeting.ics examples/work_meeting.ics
   ```

4. **Verify Resource Content & ETag**:
   ```bash
   icaldav client get http://127.0.0.1:8888/work/meeting.ics
   ```

5. **Clean Up & Stop Server**:
   Delete resource and terminate the server task:
   ```bash
   icaldav client delete http://127.0.0.1:8888/work/meeting.ics
   ```

---

## Project Standard Scripts

| Script | Action |
| :--- | :--- |
| `./script/test` | Runs full pytest suite (including XML snapshots and loopback tests). |
| `./script/lint` | Runs ruff check, ruff format, ty check, codespell, and yamllint. |
| `./script/bootstrap` | Re-initializes virtual environment and installs CLI entry points. |
