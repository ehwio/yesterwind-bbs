"""Tests for database models and engine."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from yesterwind_bbs.db.models import (
    AccessLevel,
    Base,
    FileArea,
    FileEntry,
    Message,
    MessageBoard,
    Session,
    TerminalPreference,
    User,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
async def db_session():
    """In-memory SQLite session for each test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def user(db_session):
    u = User(username="testuser", password_hash="hashed", access_level=AccessLevel.USER)
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


@pytest.fixture
async def board(db_session):
    b = MessageBoard(name="General", description="General discussion")
    db_session.add(b)
    await db_session.commit()
    await db_session.refresh(b)
    return b


@pytest.fixture
async def area(db_session):
    a = FileArea(name="Games", description="Game files", path="games")
    db_session.add(a)
    await db_session.commit()
    await db_session.refresh(a)
    return a


# ── AccessLevel ───────────────────────────────────────────────────────────────


class TestAccessLevel:
    def test_constants(self):
        assert AccessLevel.NEW < AccessLevel.USER < AccessLevel.SYSOP

    def test_new_is_zero(self):
        assert AccessLevel.NEW == 0

    def test_user_is_ten(self):
        assert AccessLevel.USER == 10

    def test_sysop_is_two_hundred(self):
        assert AccessLevel.SYSOP == 200


# ── User model ────────────────────────────────────────────────────────────────


class TestUser:
    async def test_create_user(self, db_session):
        u = User(username="alice", password_hash="bcrypt_hash")
        db_session.add(u)
        await db_session.commit()
        assert u.id is not None
        assert u.access_level == AccessLevel.NEW
        assert u.is_active is True
        assert u.login_count == 0

    async def test_default_terminal(self, db_session):
        u = User(username="bob", password_hash="x")
        db_session.add(u)
        await db_session.commit()
        assert u.terminal == TerminalPreference.ANSI.value
        assert u.screen_width == 80
        assert u.screen_lines == 24

    async def test_is_sysop_property(self):
        regular = User(username="r", password_hash="x", access_level=AccessLevel.USER)
        sysop = User(username="s", password_hash="x", access_level=AccessLevel.SYSOP)
        new = User(username="n", password_hash="x", access_level=AccessLevel.NEW)

        assert not regular.is_sysop
        assert sysop.is_sysop
        assert not new.is_sysop

    async def test_is_validated_property(self):
        regular = User(username="r", password_hash="x", access_level=AccessLevel.USER)
        new = User(username="n", password_hash="x", access_level=AccessLevel.NEW)

        assert regular.is_validated
        assert not new.is_validated

    async def test_username_unique(self, db_session):
        db_session.add(User(username="dupe", password_hash="x"))
        await db_session.commit()
        db_session.add(User(username="dupe", password_hash="y"))
        with pytest.raises(Exception):
            await db_session.commit()

    async def test_created_at_set_automatically(self, db_session):
        u = User(username="ts", password_hash="x")
        db_session.add(u)
        await db_session.commit()
        assert u.created_at is not None

    async def test_repr(self):
        u = User(username="alice", password_hash="x", access_level=10)
        assert "alice" in repr(u)
        assert "10" in repr(u)


# ── MessageBoard model ────────────────────────────────────────────────────────


class TestMessageBoard:
    async def test_create_board(self, db_session):
        b = MessageBoard(name="Tech Talk", description="Technology discussion")
        db_session.add(b)
        await db_session.commit()
        assert b.id is not None
        assert b.is_active is True
        assert b.read_level == AccessLevel.USER
        assert b.post_level == AccessLevel.USER

    async def test_board_name_unique(self, db_session):
        db_session.add(MessageBoard(name="Unique"))
        await db_session.commit()
        db_session.add(MessageBoard(name="Unique"))
        with pytest.raises(Exception):
            await db_session.commit()

    async def test_repr(self):
        b = MessageBoard(name="TestBoard")
        assert "TestBoard" in repr(b)

    async def test_sysop_only_board(self, db_session):
        b = MessageBoard(
            name="Sysop Only",
            read_level=AccessLevel.SYSOP,
            post_level=AccessLevel.SYSOP,
        )
        db_session.add(b)
        await db_session.commit()
        assert b.read_level == AccessLevel.SYSOP


# ── Message model ─────────────────────────────────────────────────────────────


class TestMessage:
    async def test_create_message(self, db_session, user, board):
        m = Message(
            board_id=board.id,
            author_id=user.id,
            subject="Hello world",
            body="This is a test message.",
        )
        db_session.add(m)
        await db_session.commit()
        assert m.id is not None
        assert m.is_deleted is False
        assert m.reply_to_id is None
        assert m.created_at is not None

    async def test_threaded_reply(self, db_session, user, board):
        parent = Message(board_id=board.id, author_id=user.id, subject="Original", body="Body")
        db_session.add(parent)
        await db_session.commit()

        reply = Message(
            board_id=board.id,
            author_id=user.id,
            subject="Re: Original",
            body="Reply body",
            reply_to_id=parent.id,
        )
        db_session.add(reply)
        await db_session.commit()
        assert reply.reply_to_id == parent.id

    async def test_soft_delete(self, db_session, user, board):
        m = Message(board_id=board.id, author_id=user.id, subject="X", body="Y")
        db_session.add(m)
        await db_session.commit()

        m.is_deleted = True
        await db_session.commit()
        assert m.is_deleted is True

    async def test_repr(self):
        m = Message(subject="My Subject", body="body")
        assert "My Subject" in repr(m)


# ── FileArea model ────────────────────────────────────────────────────────────


class TestFileArea:
    async def test_create_area(self, db_session):
        a = FileArea(name="Utilities", description="Utility software", path="utils")
        db_session.add(a)
        await db_session.commit()
        assert a.id is not None
        assert a.is_active is True
        assert a.read_level == AccessLevel.USER
        assert a.upload_level == AccessLevel.USER

    async def test_area_name_unique(self, db_session):
        db_session.add(FileArea(name="Dupes", path="d1"))
        await db_session.commit()
        db_session.add(FileArea(name="Dupes", path="d2"))
        with pytest.raises(Exception):
            await db_session.commit()

    async def test_repr(self):
        a = FileArea(name="Demos", path="demos")
        assert "Demos" in repr(a)


# ── FileEntry model ───────────────────────────────────────────────────────────


class TestFileEntry:
    async def test_create_file_entry(self, db_session, user, area):
        f = FileEntry(
            area_id=area.id,
            uploader_id=user.id,
            stored_name="abc123.zip",
            display_name="SuperGame.zip",
            description="A great game",
            size_bytes=102400,
            sha256="a" * 64,
        )
        db_session.add(f)
        await db_session.commit()
        assert f.id is not None
        assert f.download_count == 0
        assert f.is_active is True

    async def test_anonymous_upload(self, db_session, area):
        """uploader_id is nullable for sysop imports."""
        f = FileEntry(
            area_id=area.id,
            uploader_id=None,
            stored_name="legacy.zip",
            display_name="OldFile.zip",
            size_bytes=512,
        )
        db_session.add(f)
        await db_session.commit()
        assert f.uploader_id is None

    async def test_stored_name_unique(self, db_session, area):
        db_session.add(FileEntry(area_id=area.id, stored_name="dup.zip", display_name="A.zip"))
        await db_session.commit()
        db_session.add(FileEntry(area_id=area.id, stored_name="dup.zip", display_name="B.zip"))
        with pytest.raises(Exception):
            await db_session.commit()

    async def test_display_name_unique_per_area(self, db_session, area):
        db_session.add(FileEntry(area_id=area.id, stored_name="s1.zip", display_name="Same.zip"))
        await db_session.commit()
        db_session.add(FileEntry(area_id=area.id, stored_name="s2.zip", display_name="Same.zip"))
        with pytest.raises(Exception):
            await db_session.commit()

    async def test_repr(self):
        f = FileEntry(display_name="Cool.zip", size_bytes=1024)
        assert "Cool.zip" in repr(f)
        assert "1024" in repr(f)


# ── Session model ─────────────────────────────────────────────────────────────


class TestSessionModel:
    async def test_create_session(self, db_session, user):
        s = Session(
            user_id=user.id,
            remote_addr="192.168.1.42",
            node_number=1,
            terminal="ansi",
        )
        db_session.add(s)
        await db_session.commit()
        assert s.id is not None
        assert s.disconnected_at is None
        assert s.connected_at is not None

    async def test_pre_login_session(self, db_session):
        """Session before login has no user_id."""
        s = Session(remote_addr="10.0.0.1", node_number=2)
        db_session.add(s)
        await db_session.commit()
        assert s.user_id is None

    async def test_ipv6_address(self, db_session):
        s = Session(remote_addr="2001:db8::1", node_number=3)
        db_session.add(s)
        await db_session.commit()
        assert s.remote_addr == "2001:db8::1"

    async def test_repr(self):
        s = Session(node_number=5, remote_addr="1.2.3.4")
        assert "5" in repr(s)
        assert "1.2.3.4" in repr(s)


# ── Engine helpers ────────────────────────────────────────────────────────────


class TestInitDb:
    async def test_init_db_creates_tables(self):
        """init_db should run without error against a fresh in-memory DB."""
        import os

        os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

        # Re-import to use the in-memory URL
        from yesterwind_bbs.db.engine import init_db

        await init_db()  # should not raise
