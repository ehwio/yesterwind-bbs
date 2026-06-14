# Yesterwind BBS

A retro-style telnet BBS server with support for ANSI/VT100, ATASCII (Atari 8-bit), PETSCII (Commodore 64/128), and Amiga terminals. File transfers use [yesterwind-xyzmodem](https://github.com/ehwio/yesterwind-xyzmodem).

## Quick start (Docker)

```bash
cp .env.example .env
# Edit .env — at minimum generate a SECRET_KEY:
#   python -c "import secrets; print(secrets.token_hex(32))"
docker compose up -d
```

**First run:** no accounts exist yet. Before connecting, create the initial sysop account:

```bash
docker compose exec bbs bbs-sysop
```

Then connect with any telnet client:

```bash
telnet localhost 23
```

## Sysop console

```bash
docker compose exec bbs bbs-sysop
```

## Configuration

All configuration is via environment variables. See `.env.example` for the full list.

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///data/bbs.db` | Database connection string |
| `BBS_NAME` | `Yesterwind BBS` | Name shown at login |
| `BBS_PORT` | `23` | TCP port |
| `SECRET_KEY` | *(required)* | Session signing key — generate with `python -c "import secrets; print(secrets.token_hex(32))"` |

## Database backends

SQLite is the default. For PostgreSQL:

```bash
pip install "yesterwind-bbs[postgres]"
# Set DATABASE_URL=postgresql+asyncpg://user:pass@host/bbs
```

## Supported terminals

| Choice | Terminal | Platform |
|---|---|---|
| 1 | ANSI/VT100 | DOS, Windows, Mac, Linux, Amiga |
| 2 | ATASCII | Atari 8-bit (400/800/XL/XE) |
| 3 | PETSCII | Commodore 64/128 |
| 4 | Plain ASCII | Any |

## License

MIT
