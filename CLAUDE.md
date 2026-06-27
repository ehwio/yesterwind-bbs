# Yesterwind BBS — Claude Code Guide

This file is read automatically by Claude Code at the start of every session.

## Project overview

Yesterwind BBS is an async Python telnet BBS server. It supports ANSI/VT100,
ATASCII (Atari 8-bit), PETSCII (Commodore 64/128), and plain ASCII terminals.
File transfers use the companion library
[yesterwind-xyzmodem](https://github.com/ehwio/yesterwind-xyzmodem).

Runtime: Python 3.10+, asyncio, SQLAlchemy 2 (async), aiosqlite / asyncpg.
Packaging: uv + hatchling. CI: GitHub Actions (ruff, pytest-cov).

## Repository layout

```
src/yesterwind_bbs/
  cli.py          entry point → asyncio.run(server.serve())
  server.py       TCP listener, calls init_db() on startup
  session.py      per-connection state machine (menu, login, file areas, …)
  telnet.py       passive Telnet option negotiation (TTYPE detection)
  auth.py         bcrypt login, password validation, session tokens
  config.py       env-var config (DATABASE_URL, BBS_NAME, BBS_PORT, SECRET_KEY, FILES_DIR)
  files.py        file area CRUD, xyzmodem transfer integration, sysop import/rescan
  messages.py     message board CRUD
  db/
    engine.py     async engine + get_session() context manager, init_db()
    models.py     SQLAlchemy models: User, FileArea, FileEntry, MessageBoard, Message, Session
  terminal/
    base.py       Terminal ABC + TerminalType enum + TERMINAL_MENU bytes
    ansi.py       ANSI/VT100 + CP437
    atascii.py    Atari 8-bit
    petscii.py    Commodore 64/128
    ascii.py      plain ASCII fallback
  sysop/
    console.py    rich-based interactive sysop console (bbs-sysop entry point)

tests/            pytest suite — mirrors src layout
docs/             architecture specs (doors-spec.md, …)
```

## Development workflow

```bash
uv sync                         # install all deps including dev
uv run bbs                      # run the server locally
uv run bbs-sysop                # run the sysop console
uv run pytest                   # full test suite + coverage (≥47% required)
uv run ruff check src/ tests/   # lint
uv run ruff format src/ tests/  # format
```

**Always run ruff check + ruff format + pytest before pushing.** CI enforces
all three. Two past CI failures resulted from skipping this step.

## Branch and PR workflow

- `main` is protected — never push directly.
- Branch naming: `feature/<slug>`, `fix/<slug>`, `docs/<slug>`.
- Open a PR and let CI pass before merging.
- Use `gh pr merge --squash` for clean history.

## Key design decisions

**Async throughout.** Every I/O path is `async`/`await`. Never use blocking
calls (`open()`, `requests`, `time.sleep()`) inside coroutines — use
`asyncio` equivalents or run in an executor.

**Terminal-agnostic I/O.** All text that reaches the wire goes through a
`Terminal` codec (`session.conn.send()`). Never write raw ANSI escape codes
outside `terminal/ansi.py`.

**Database access via `get_session()`.** Always use the async context manager
from `db/engine.py`. Never hold a session across `await` points that aren't
within a single transaction.

**File entries are DB-backed.** `files.py` tracks every file in the
`file_entries` table. Files on disk that have no DB row are invisible to users.
Use `bbs-sysop` → File Areas → Import files or Rescan area to register
pre-existing files.

**Telnet healthcheck handling.** The Docker healthcheck connects and immediately
closes. `telnet.py:passive_detect()` returns `None` on empty read to avoid
`AssertionError: feed_data after feed_eof`.

**CRLF normalisation.** Linux telnet sends `\r\n`. `session.py:read_line()`
absorbs the trailing `\n` after a `\r`-triggered ENTER with a 50 ms lookahead.

## Testing patterns

- Use `pytest-asyncio` with `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` needed.
- Patch `sys.modules["yesterwind_bbs.db.engine"].engine` (not the re-exported
  symbol) when you need an isolated in-memory engine in tests.
- Coverage threshold is 47%. Add tests when adding new modules.

## Planned features (not yet implemented)

See `docs/doors-spec.md` for the doors subsystem design.
