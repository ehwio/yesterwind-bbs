"""
Tests for sysop console helpers.

We don't try to simulate interactive prompts — instead we test the
formatting helpers, the pure logic paths, and that every public entry
point is importable and callable with controlled inputs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from yesterwind_bbs.db.models import AccessLevel, Base, User
from yesterwind_bbs.sysop.console import (
    _first_run_setup,
    _fmt_dt,
    _fmt_level,
    _is_first_run,
)


class TestFmtLevel:
    def test_sysop_level(self):
        out = _fmt_level(AccessLevel.SYSOP)
        assert "SYSOP" in out
        assert "200" in out

    def test_user_level(self):
        out = _fmt_level(AccessLevel.USER)
        assert "USER" in out
        assert "10" in out

    def test_new_level(self):
        out = _fmt_level(AccessLevel.NEW)
        assert "NEW" in out
        assert "0" in out

    def test_custom_high_level(self):
        # custom level above SYSOP still renders as SYSOP tier
        out = _fmt_level(255)
        assert "SYSOP" in out

    def test_custom_mid_level(self):
        # value between USER and SYSOP renders as USER tier
        out = _fmt_level(50)
        assert "USER" in out

    def test_returns_string(self):
        assert isinstance(_fmt_level(AccessLevel.USER), str)


class TestFmtDt:
    def test_none_returns_never(self):
        out = _fmt_dt(None)
        assert "never" in out

    def test_datetime_formats(self):
        dt = datetime(2025, 6, 1, 12, 30, tzinfo=timezone.utc)
        out = _fmt_dt(dt)
        assert "2025" in out
        assert "06" in out
        assert "01" in out

    def test_returns_string(self):
        assert isinstance(_fmt_dt(None), str)
        assert isinstance(_fmt_dt(datetime.now(timezone.utc)), str)


class TestImports:
    """Verify every public symbol used by the menus is importable."""

    def test_console_importable(self):
        from yesterwind_bbs.sysop.console import console

        assert console is not None

    def test_main_importable(self):
        from yesterwind_bbs.sysop.console import main

        assert callable(main)

    def test_helper_functions_importable(self):
        import inspect

        from yesterwind_bbs.sysop.console import (
            _areas_menu,
            _authenticate,
            _boards_menu,
            _main_menu,
            _show_nodes,
            _show_status,
            _users_menu,
        )

        for fn in [
            _authenticate,
            _boards_menu,
            _areas_menu,
            _users_menu,
            _main_menu,
            _show_status,
            _show_nodes,
        ]:
            assert inspect.iscoroutinefunction(fn)


# ── First-run helpers ─────────────────────────────────────────────────────────


@pytest.fixture
async def empty_db_session():
    """In-memory SQLite engine with tables but no rows."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def populated_db_session(empty_db_session):
    """Session with one user already present."""
    from yesterwind_bbs.auth import hash_password

    user = User(
        username="sysop",
        password_hash=hash_password("S3cr3t!xY"),
        access_level=AccessLevel.SYSOP,
    )
    empty_db_session.add(user)
    await empty_db_session.commit()
    yield empty_db_session


class TestIsFirstRun:
    async def test_returns_true_when_no_users(self, empty_db_session):
        with patch(
            "yesterwind_bbs.sysop.console.get_session",
            return_value=empty_db_session,
        ):
            # get_session is an async context manager; patch properly
            pass
        # Test via direct DB call instead — patch the session factory
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _mock_get_session():
            yield empty_db_session

        with patch("yesterwind_bbs.sysop.console.get_session", _mock_get_session):
            result = await _is_first_run()
        assert result is True

    async def test_returns_false_when_users_exist(self, populated_db_session):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _mock_get_session():
            yield populated_db_session

        with patch("yesterwind_bbs.sysop.console.get_session", _mock_get_session):
            result = await _is_first_run()
        assert result is False


class TestFirstRunSetup:
    async def test_creates_sysop_user(self, empty_db_session):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _mock_get_session():
            yield empty_db_session

        prompts = iter(["admin", "S3cr3t!xY", "S3cr3t!xY"])
        prompt_patch = patch(
            "yesterwind_bbs.sysop.console.Prompt.ask",
            side_effect=lambda *a, **kw: next(prompts),
        )
        with (
            patch("yesterwind_bbs.sysop.console.get_session", _mock_get_session),
            prompt_patch,
        ):
            user = await _first_run_setup()

        assert user.username == "admin"
        assert user.access_level == AccessLevel.SYSOP

    async def test_retries_on_empty_username(self, empty_db_session):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _mock_get_session():
            yield empty_db_session

        # First username is blank, second is valid
        prompts = iter(["", "sysop", "S3cr3t!xY", "S3cr3t!xY"])
        prompt_patch = patch(
            "yesterwind_bbs.sysop.console.Prompt.ask",
            side_effect=lambda *a, **kw: next(prompts),
        )
        with (
            patch("yesterwind_bbs.sysop.console.get_session", _mock_get_session),
            prompt_patch,
        ):
            user = await _first_run_setup()

        assert user.username == "sysop"

    async def test_retries_on_password_mismatch(self, empty_db_session):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _mock_get_session():
            yield empty_db_session

        # Passwords don't match on first attempt, then they do
        prompts = iter(["admin", "S3cr3t!xY", "wrong", "admin", "S3cr3t!xY", "S3cr3t!xY"])
        prompt_patch = patch(
            "yesterwind_bbs.sysop.console.Prompt.ask",
            side_effect=lambda *a, **kw: next(prompts),
        )
        with (
            patch("yesterwind_bbs.sysop.console.get_session", _mock_get_session),
            prompt_patch,
        ):
            user = await _first_run_setup()

        assert user.username == "admin"
