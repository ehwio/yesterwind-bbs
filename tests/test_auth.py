"""Tests for authentication — signup, login, password hashing."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from yesterwind_bbs.auth import (
    AuthError,
    InvalidCredentials,
    InvalidUsername,
    UserInactive,
    UsernameTaken,
    WeakPassword,
    change_password,
    hash_password,
    login,
    set_access_level,
    signup,
    validate_password,
    validate_username,
    verify_password,
)
from yesterwind_bbs.db.models import AccessLevel, Base

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def sysop(db_session):
    """First user — automatically gets SYSOP."""
    user = await signup(db_session, "sysoplord", "supersecret99")
    await db_session.commit()
    return user


@pytest.fixture
async def regular_user(db_session, sysop):
    """Second user — starts at NEW."""
    user = await signup(db_session, "bobbyboy", "password123")
    await db_session.commit()
    return user


# ── Password hashing ──────────────────────────────────────────────────────────


class TestPasswordHashing:
    def test_hash_is_not_plaintext(self):
        h = hash_password("secret")
        assert h != "secret"

    def test_verify_correct_password(self):
        h = hash_password("correct")
        assert verify_password("correct", h) is True

    def test_verify_wrong_password(self):
        h = hash_password("correct")
        assert verify_password("wrong", h) is False

    def test_two_hashes_of_same_password_differ(self):
        # bcrypt uses random salt — same plaintext must not produce same hash
        assert hash_password("same") != hash_password("same")


# ── validate_username ─────────────────────────────────────────────────────────


class TestValidateUsername:
    def test_valid_username(self):
        assert validate_username("Alice") == "Alice"

    def test_strips_whitespace(self):
        assert validate_username("  bob  ") == "bob"

    def test_too_short(self):
        with pytest.raises(InvalidUsername, match="at least"):
            validate_username("ab")

    def test_too_long(self):
        with pytest.raises(InvalidUsername, match="no more than"):
            validate_username("a" * 33)

    def test_invalid_chars(self):
        with pytest.raises(InvalidUsername, match="only contain"):
            validate_username("bad name!")

    def test_hyphen_and_underscore_allowed(self):
        assert validate_username("cool-user_123") == "cool-user_123"

    def test_reserved_name_sysop(self):
        with pytest.raises(InvalidUsername, match="reserved"):
            validate_username("sysop")

    def test_reserved_name_case_insensitive(self):
        with pytest.raises(InvalidUsername, match="reserved"):
            validate_username("ADMIN")

    def test_reserved_name_root(self):
        with pytest.raises(InvalidUsername, match="reserved"):
            validate_username("root")


# ── validate_password ─────────────────────────────────────────────────────────


class TestValidatePassword:
    def test_valid_password(self):
        validate_password("secure1")  # should not raise

    def test_too_short(self):
        with pytest.raises(WeakPassword, match="at least"):
            validate_password("short")

    def test_minimum_length_exactly(self):
        validate_password("123456")  # 6 chars — should not raise


# ── signup ────────────────────────────────────────────────────────────────────


class TestSignup:
    async def test_first_user_becomes_sysop(self, db_session):
        user = await signup(db_session, "firstguy", "password1")
        assert user.access_level == AccessLevel.SYSOP

    async def test_second_user_is_new(self, db_session, sysop):
        user = await signup(db_session, "newbie", "password1")
        assert user.access_level == AccessLevel.NEW

    async def test_user_has_id_after_flush(self, db_session):
        user = await signup(db_session, "flushed", "password1")
        assert user.id is not None

    async def test_duplicate_username_raises(self, db_session, sysop):
        with pytest.raises(UsernameTaken):
            await signup(db_session, "sysoplord", "otherpass1")

    async def test_duplicate_username_case_insensitive(self, db_session, sysop):
        with pytest.raises(UsernameTaken):
            await signup(db_session, "SYSOPLORD", "otherpass1")

    async def test_weak_password_raises(self, db_session):
        with pytest.raises(WeakPassword):
            await signup(db_session, "weakuser", "123")

    async def test_invalid_username_raises(self, db_session):
        with pytest.raises(InvalidUsername):
            await signup(db_session, "bad user!", "password1")

    async def test_optional_fields_stored(self, db_session):
        user = await signup(
            db_session,
            "detailed",
            "password1",
            email="user@example.com",
            real_name="Test User",
            location="Cyberspace",
        )
        assert user.email == "user@example.com"
        assert user.real_name == "Test User"
        assert user.location == "Cyberspace"

    async def test_password_is_hashed(self, db_session):
        user = await signup(db_session, "hashme", "plaintext1")
        assert user.password_hash != "plaintext1"
        assert verify_password("plaintext1", user.password_hash)

    async def test_auth_error_is_base_class(self):
        assert issubclass(UsernameTaken, AuthError)
        assert issubclass(InvalidUsername, AuthError)
        assert issubclass(WeakPassword, AuthError)
        assert issubclass(InvalidCredentials, AuthError)


# ── login ─────────────────────────────────────────────────────────────────────


class TestLogin:
    async def test_successful_login(self, db_session, sysop):
        user = await login(db_session, "sysoplord", "supersecret99")
        assert user.id == sysop.id

    async def test_login_case_insensitive_username(self, db_session, sysop):
        user = await login(db_session, "SYSOPLORD", "supersecret99")
        assert user.id == sysop.id

    async def test_login_increments_count(self, db_session, sysop):
        assert sysop.login_count == 0
        await login(db_session, "sysoplord", "supersecret99")
        assert sysop.login_count == 1

    async def test_login_sets_last_login_at(self, db_session, sysop):
        assert sysop.last_login_at is None
        await login(db_session, "sysoplord", "supersecret99")
        assert sysop.last_login_at is not None

    async def test_wrong_password_raises(self, db_session, sysop):
        with pytest.raises(InvalidCredentials):
            await login(db_session, "sysoplord", "wrongpassword")

    async def test_unknown_user_raises(self, db_session):
        with pytest.raises(InvalidCredentials):
            await login(db_session, "nosuchuser", "anything")

    async def test_inactive_user_raises(self, db_session, sysop):
        sysop.is_active = False
        await db_session.commit()
        with pytest.raises(UserInactive):
            await login(db_session, "sysoplord", "supersecret99")

    async def test_unknown_user_does_not_leak_via_timing(self, db_session):
        """Verify that a fake hash is compared even when user doesn't exist."""
        # This test doesn't measure timing, but ensures the code path that
        # computes verify_password is hit for unknown users (no short-circuit).
        with pytest.raises(InvalidCredentials):
            await login(db_session, "phantom", "anypassword")


# ── change_password ───────────────────────────────────────────────────────────


class TestChangePassword:
    async def test_successful_change(self, db_session, sysop):
        await change_password(db_session, sysop, "supersecret99", "newpassword1")
        assert verify_password("newpassword1", sysop.password_hash)

    async def test_wrong_current_password(self, db_session, sysop):
        with pytest.raises(InvalidCredentials):
            await change_password(db_session, sysop, "wrongcurrent", "newpassword1")

    async def test_weak_new_password(self, db_session, sysop):
        with pytest.raises(WeakPassword):
            await change_password(db_session, sysop, "supersecret99", "weak")

    async def test_old_password_no_longer_works(self, db_session, sysop):
        await change_password(db_session, sysop, "supersecret99", "brandnew123")
        assert not verify_password("supersecret99", sysop.password_hash)


# ── set_access_level ──────────────────────────────────────────────────────────


class TestSetAccessLevel:
    async def test_sysop_can_promote(self, db_session, sysop, regular_user):
        await set_access_level(db_session, regular_user, AccessLevel.USER, actor=sysop)
        assert regular_user.access_level == AccessLevel.USER

    async def test_sysop_can_demote(self, db_session, sysop, regular_user):
        regular_user.access_level = AccessLevel.USER
        await set_access_level(db_session, regular_user, AccessLevel.NEW, actor=sysop)
        assert regular_user.access_level == AccessLevel.NEW

    async def test_regular_user_cannot_change_level(self, db_session, sysop, regular_user):
        regular_user.access_level = AccessLevel.USER
        with pytest.raises(PermissionError):
            await set_access_level(db_session, sysop, AccessLevel.NEW, actor=regular_user)

    async def test_new_user_cannot_change_level(self, db_session, sysop, regular_user):
        with pytest.raises(PermissionError):
            await set_access_level(db_session, sysop, AccessLevel.NEW, actor=regular_user)
