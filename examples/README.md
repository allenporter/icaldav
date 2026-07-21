# icaldav Examples

This directory contains sample `.ics` iCalendar files and example workflows for testing `icaldav` CLI commands and server synchronization.

---

## Example Files

* `examples/work_meeting.ics`: Standard single work meeting event (`VEVENT`).
* `examples/recurring_sync.ics`: Weekly recurring standup meeting (`VEVENT` with `RRULE`).
* `examples/todo_task.ics`: Action item to-do task (`VTODO`).

---

## Quick Start CLI Workflow

### 1. Launch Server
In Terminal 1:
```bash
icaldav serve --port 8080
```

### 2. Query Collection Listing (`PROPFIND`)
In Terminal 2:
```bash
icaldav client propfind http://127.0.0.1:8080/work
```

### 3. Upload Sample Events (`PUT`)
```bash
# Upload work meeting
icaldav client put http://127.0.0.1:8080/work/meeting.ics examples/work_meeting.ics

# Upload recurring sync
icaldav client put http://127.0.0.1:8080/work/recurring.ics examples/recurring_sync.ics

# Upload to-do task
icaldav client put http://127.0.0.1:8080/work/task.ics examples/todo_task.ics
```

### 4. Fetch Calendar Resource (`GET`)
```bash
icaldav client get http://127.0.0.1:8080/work/meeting.ics
```

### 5. Re-Query Collection Listing (`PROPFIND`)
```bash
icaldav client propfind http://127.0.0.1:8080/work --depth 1
```

### 6. Delete Resource (`DELETE`)
```bash
icaldav client delete http://127.0.0.1:8080/work/meeting.ics
```
