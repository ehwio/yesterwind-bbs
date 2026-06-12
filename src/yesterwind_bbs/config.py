"""Runtime configuration loaded from environment / .env file."""

from __future__ import annotations

import os
import secrets

from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(f"Required environment variable {key!r} is not set")
    return val


def _default(key: str, default: str) -> str:
    return os.environ.get(key, default)


DATABASE_URL: str = _default("DATABASE_URL", "sqlite+aiosqlite:///data/bbs.db")
FILES_DIR: str = _default("FILES_DIR", "data/files")

BBS_NAME: str = _default("BBS_NAME", "Yesterwind BBS")
BBS_SYSOP: str = _default("BBS_SYSOP", "Sysop")
BBS_HOSTNAME: str = _default("BBS_HOSTNAME", "localhost")
BBS_PORT: int = int(_default("BBS_PORT", "23"))
BBS_MAX_CONNECTIONS: int = int(_default("BBS_MAX_CONNECTIONS", "64"))

# Warn loudly if the secret key is the placeholder — never silently use it
_raw_secret = os.environ.get("SECRET_KEY", "")
if not _raw_secret or _raw_secret == "change-me-generate-a-real-secret-key":
    import warnings

    warnings.warn(
        "SECRET_KEY is not set or is the example placeholder. "
        'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"',
        stacklevel=1,
    )
    SECRET_KEY: str = secrets.token_hex(32)  # ephemeral fallback — sessions won't survive restart
else:
    SECRET_KEY = _raw_secret
