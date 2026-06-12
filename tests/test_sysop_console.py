"""
Tests for sysop console helpers.

We don't try to simulate interactive prompts — instead we test the
formatting helpers, the pure logic paths, and that every public entry
point is importable and callable with controlled inputs.
"""

from __future__ import annotations

from datetime import datetime, timezone

from yesterwind_bbs.db.models import AccessLevel
from yesterwind_bbs.sysop.console import (
    _fmt_dt,
    _fmt_level,
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
