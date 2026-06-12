"""
User authentication — signup, login, password hashing.

First user to sign up automatically becomes sysop (no chicken-and-egg
problem for fresh installs). Subsequent users start at AccessLevel.NEW
and must be validated by the sysop.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import bcrypt as _bcrypt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yesterwind_bbs.db.models import AccessLevel, User

# ── Password hashing ──────────────────────────────────────────────────────────


def hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


# ── Validation constants ──────────────────────────────────────────────────────

USERNAME_MIN = 3
USERNAME_MAX = 32
PASSWORD_MIN = 6

# Allowed: letters, digits, underscore, hyphen
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Names that could confuse users or impersonate system accounts
_RESERVED = frozenset(
    {
        "sysop",
        "admin",
        "root",
        "system",
        "bbs",
        "anonymous",
        "guest",
        "postmaster",
        "null",
        "nobody",
    }
)


# ── Exceptions ────────────────────────────────────────────────────────────────


class AuthError(Exception):
    """Base class for all auth errors."""


class UsernameTaken(AuthError):
    """Raised when the requested username is already registered."""


class InvalidUsername(AuthError):
    """Raised when the username fails validation."""


class WeakPassword(AuthError):
    """Raised when the password is too short or otherwise unacceptable."""


class InvalidCredentials(AuthError):
    """Raised when username/password do not match."""


class UserInactive(AuthError):
    """Raised when a valid user's account has been disabled."""


# ── Validation helpers ────────────────────────────────────────────────────────


def validate_username(username: str) -> str:
    """
    Normalise and validate a username.
    Returns the normalised form (stripped, original case preserved).
    Raises InvalidUsername on any problem.
    """
    username = username.strip()
    if len(username) < USERNAME_MIN:
        raise InvalidUsername(f"Username must be at least {USERNAME_MIN} characters.")
    if len(username) > USERNAME_MAX:
        raise InvalidUsername(f"Username must be no more than {USERNAME_MAX} characters.")
    if not _USERNAME_RE.match(username):
        raise InvalidUsername(
            "Username may only contain letters, digits, hyphens, and underscores."
        )
    if username.lower() in _RESERVED:
        raise InvalidUsername(f"'{username}' is a reserved name.")
    return username


def validate_password(password: str) -> None:
    """Raises WeakPassword if the password doesn't meet requirements."""
    if len(password) < PASSWORD_MIN:
        raise WeakPassword(f"Password must be at least {PASSWORD_MIN} characters.")


# ── Core auth functions ───────────────────────────────────────────────────────


async def _user_count(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(User))
    return result.scalar_one()


async def signup(
    session: AsyncSession,
    username: str,
    password: str,
    *,
    email: str | None = None,
    real_name: str | None = None,
    location: str | None = None,
) -> User:
    """
    Register a new user.

    The very first user on a fresh install is promoted to SYSOP automatically.
    All subsequent users start at AccessLevel.NEW pending sysop validation.

    Raises:
        InvalidUsername   — bad format or reserved name
        WeakPassword      — password too short
        UsernameTaken     — username already exists (case-insensitive)
    """
    username = validate_username(username)
    validate_password(password)

    # Case-insensitive uniqueness check
    existing = await session.execute(
        select(User).where(func.lower(User.username) == username.lower())
    )
    if existing.scalar_one_or_none() is not None:
        raise UsernameTaken(f"'{username}' is already taken.")

    is_first_user = await _user_count(session) == 0
    level = AccessLevel.SYSOP if is_first_user else AccessLevel.NEW

    user = User(
        username=username,
        password_hash=hash_password(password),
        email=email,
        real_name=real_name,
        location=location,
        access_level=level,
    )
    session.add(user)
    await session.flush()  # populate user.id without committing
    return user


async def login(
    session: AsyncSession,
    username: str,
    password: str,
) -> User:
    """
    Authenticate a user by username and password.

    Updates last_login_at and increments login_count on success.

    Raises:
        InvalidCredentials — username not found or password wrong
        UserInactive       — account is disabled
    """
    result = await session.execute(
        select(User).where(func.lower(User.username) == username.strip().lower())
    )
    user = result.scalar_one_or_none()

    # Verify password even if user not found (timing-safe against enumeration)
    dummy_hash = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ012346"
    candidate_hash = user.password_hash if user else dummy_hash
    if not verify_password(password, candidate_hash) or user is None:
        raise InvalidCredentials("Invalid username or password.")

    if not user.is_active:
        raise UserInactive("This account has been disabled.")

    user.last_login_at = datetime.now(timezone.utc)
    user.login_count += 1
    await session.flush()
    return user


async def change_password(
    session: AsyncSession,
    user: User,
    current_password: str,
    new_password: str,
) -> None:
    """
    Change a user's password after verifying the current one.

    Raises:
        InvalidCredentials — current password is wrong
        WeakPassword       — new password is too short
    """
    if not verify_password(current_password, user.password_hash):
        raise InvalidCredentials("Current password is incorrect.")
    validate_password(new_password)
    user.password_hash = hash_password(new_password)
    await session.flush()


async def set_access_level(
    session: AsyncSession,
    target_user: User,
    level: int,
    *,
    actor: User,
) -> None:
    """
    Change a user's access level. Only sysops may do this.

    Raises:
        PermissionError — actor is not a sysop
    """
    if not actor.is_sysop:
        raise PermissionError("Only sysops can change access levels.")
    target_user.access_level = level
    await session.flush()
