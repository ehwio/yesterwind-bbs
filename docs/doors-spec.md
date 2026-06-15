# Yesterwind BBS — Door Specification

Doors are external programs or Python plugins that integrate with the BBS to provide games, utilities, and other interactive experiences. The BBS manages launching, I/O bridging, user context, and persistence hooks so door authors can focus on the experience itself.

---

## Discovery

Doors live under `DOORS_DIR` (default: `data/doors/`, configurable via env var). Each door is a subdirectory. The BBS scans this directory at startup and when the sysop triggers a reload.

```
data/doors/
  tradewars/
    door.toml          ← external process door
    tw2002             ← the executable
    data/              ← door's own persistent data
  trivia/
    door.toml          ← could also be a Python door
    door.py            ← Python door (door.toml references it)
  fortune/
    door.py            ← Python-only door (no door.toml needed)
```

A directory is recognised as a door if it contains **either** `door.toml` or `door.py` (or both). If `door.toml` is absent but `door.py` is present, the BBS uses defaults for all metadata.

---

## door.toml — manifest

```toml
# Required
name = "Trade Wars 2002"

# Optional metadata
description  = "Classic space trading game"
author       = "Martech"
version      = "3.09"

# Access control
min_access   = 10     # minimum AccessLevel to see/launch; default 10 (USER)

# Launch mode: "external" or "python" (default: "python" if door.py exists, else "external")
mode = "external"

# External process settings (mode = "external" only)
command      = ["./tw2002"]   # argv; resolved relative to the door directory
time_limit   = 3600           # seconds; 0 = no limit; default 600
encoding     = "cp437"        # stdout encoding for the door's output; default "cp437"

# Environment variables added to the door process (merged with BBS drop vars)
[env]
TW_DATA = "./data"
```

For Python doors, `door.toml` is optional. If present only `name`, `description`, `author`, `version`, and `min_access` are meaningful.

---

## Drop file — `door.json`

Written by the BBS to the door's directory immediately before launch (external doors only). The door reads it at startup.

```json
{
  "schema": 1,

  "user": {
    "username": "alice",
    "display_name": "Alice",
    "access_level": 10,
    "is_sysop": false,
    "email": "alice@example.com",
    "files_uploaded": 12,
    "files_downloaded": 34,
    "bytes_uploaded": 102400,
    "bytes_downloaded": 307200
  },

  "session": {
    "node": 1,
    "bbs_name": "Yesterwind BBS",
    "terminal": "ansi",
    "time_limit_seconds": 3600,
    "time_remaining_seconds": 3598,
    "started_at": "2026-06-15T12:00:00Z"
  }
}
```

All fields are read-only from the door's perspective. The door must not write back to `door.json`.

---

## Result file — `result.json`

Written by the door to its own directory on clean exit. The BBS reads it after the process exits. Entirely optional — if absent the BBS does nothing extra.

```json
{
  "schema": 1,

  "scores": [
    { "username": "alice", "key": "high_score", "value": 42000 },
    { "username": "alice", "key": "rank",        "value": "Rear Admiral" }
  ],

  "message": "Thanks for playing Trade Wars!"
}
```

The BBS stores score entries in a `door_scores` table keyed by `(door_slug, username, key)`. The sysop console can display and reset scores. Doors retrieve prior scores via the **Door Score API** (see below).

---

## I/O bridging (external doors)

The BBS connects the door process's `stdin` and `stdout` directly to the telnet stream with no intermediate translation. The door is responsible for its own screen rendering in whatever encoding its `door.toml` declares.

`stderr` is captured separately and appended to the BBS log at DEBUG level (tagged with the door slug).

The BBS sends a `SIGTERM` when `time_limit` is reached, followed by `SIGKILL` after 5 seconds if the process has not exited.

---

## Python Door Protocol

A Python door is a module containing a class named `Door` that implements the following interface:

```python
from yesterwind_bbs.doors import DoorSession

class Door:
    # Optional: displayed in door list if door.toml is absent
    name: str = "My Door"
    description: str = ""
    min_access: int = 10

    async def run(self, session: DoorSession) -> None:
        """Entry point. Return to exit the door cleanly."""
        ...
```

### DoorSession

```python
class DoorSession:
    # Read-only context
    user: User                  # SQLAlchemy model, detached (read-only)
    terminal: Terminal          # the active terminal codec
    bbs_name: str
    time_limit: int             # seconds; 0 = no limit
    door_dir: Path              # path to this door's directory

    # I/O — same semantics as session.py
    async def send(self, text: str) -> None: ...
    async def sendline(self, text: str = "") -> None: ...
    async def read_key(self, timeout: float | None = None) -> str: ...
    async def read_line(self, prompt: str = "", timeout: float | None = None) -> str: ...

    # Score API
    async def get_score(self, key: str, *, username: str | None = None) -> int | str | None: ...
    async def set_score(self, key: str, value: int | str, *, username: str | None = None) -> None: ...
    async def get_leaderboard(self, key: str, *, limit: int = 10) -> list[dict]: ...
```

`username` in the score methods defaults to the current user. Sysops can pass any username. Score values are stored as strings; the door is responsible for type coercion.

---

## Door Score API (external doors)

External doors that need to read or write scores mid-run can use a simple HTTP API exposed on a loopback socket. The socket path (or port) is passed as the `BBS_DOOR_API` environment variable.

```
GET  /scores/{door_slug}/{username}/{key}
     → {"value": "42000"}  or  404

PUT  /scores/{door_slug}/{username}/{key}
     body: {"value": "42000"}
     → 204

GET  /scores/{door_slug}/leaderboard/{key}?limit=10
     → [{"username": "alice", "value": "42000"}, ...]
```

Authentication: requests must include the header `X-Door-Token: <token>` where the token is written to the drop file as `session.api_token`. The token is single-use-per-session and is invalidated when the door process exits.

---

## Database schema additions

```sql
CREATE TABLE doors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT NOT NULL UNIQUE,   -- directory name
    name        TEXT NOT NULL,
    description TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT 1,
    min_access  INTEGER NOT NULL DEFAULT 10,
    run_count   INTEGER NOT NULL DEFAULT 0,
    created_at  DATETIME NOT NULL
);

CREATE TABLE door_scores (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    door_id     INTEGER NOT NULL REFERENCES doors(id),
    username    TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    updated_at  DATETIME NOT NULL,
    UNIQUE (door_id, username, key)
);

CREATE TABLE door_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    door_id     INTEGER NOT NULL REFERENCES doors(id),
    user_id     INTEGER REFERENCES users(id),
    started_at  DATETIME NOT NULL,
    ended_at    DATETIME,
    exit_code   INTEGER
);
```

---

## BBS menu integration

Doors appear in a **Doors** section of the main menu. The BBS queries the `doors` table for active doors the current user has access to and displays them in a numbered list. Selection launches the door.

```
[D] Doors
    1. Trade Wars 2002
    2. Trivia Challenge
    3. Fortune Cookie
```

---

## Sysop console additions

Under a new **Doors** menu:

- List all registered doors (slug, name, active, run count, last run)
- Toggle active/inactive
- Reload doors (re-scans `DOORS_DIR`, registers new, deactivates removed)
- View/reset scores for a door

---

## Security considerations

- External door processes run as the `bbs` OS user (same as the server) — no privilege separation by default. Sysops are responsible for vetting door software.
- The `door.json` drop file is world-readable within the container; it contains only information already known to the logged-in user.
- The Door Score API token is regenerated each session and bound to the process's lifetime.
- Doors cannot write to any BBS path outside their own `door_dir` unless the OS user permits it.

---

## Example: minimal Python door

```python
# data/doors/fortune/door.py
import random

FORTUNES = [
    "Good things come to those who wait at 2400 baud.",
    "The modem is mightier than the sword.",
    "Your carrier has been detected.",
]

class Door:
    name = "Fortune Cookie"
    description = "A random fortune, BBS style."

    async def run(self, session):
        fortune = random.choice(FORTUNES)
        await session.sendline()
        await session.sendline(f"  *** {fortune} ***")
        await session.sendline()
        await session.sendline("Press any key...")
        await session.read_key()
```

---

## Example: minimal external door (shell script)

```bash
#!/usr/bin/env bash
# data/doors/sysinfo/run.sh — reads drop file, prints system info
python3 -c "import json, sys; d=json.load(open('door.json')); print(f\"Hello {d['user']['username']}!\")"
echo "Press Enter to continue..."
read
```

```toml
# data/doors/sysinfo/door.toml
name    = "System Info"
mode    = "external"
command = ["bash", "run.sh"]
```
