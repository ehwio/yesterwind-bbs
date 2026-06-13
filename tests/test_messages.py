"""Tests for the messages module — boards, threads, posting, editing, deletion."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from yesterwind_bbs.auth import signup
from yesterwind_bbs.db.models import AccessLevel, Base
from yesterwind_bbs.messages import (
    BoardNameTaken,
    BoardNotFound,
    MessageError,
    MessageNotFound,
    PermissionDenied,
    create_board,
    delete_message,
    edit_message,
    get_board,
    get_thread,
    list_boards,
    list_thread_starters,
    message_count,
    post_message,
    update_board,
)

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
    user = await signup(db_session, "sysoplord", "supersecret99")
    await db_session.commit()
    return user


@pytest.fixture
async def user(db_session, sysop):
    u = await signup(db_session, "regularjoe", "password123")
    u.access_level = AccessLevel.USER
    await db_session.commit()
    return u


@pytest.fixture
async def new_user(db_session, sysop):
    """User at AccessLevel.NEW — below the default post/read level."""
    u = await signup(db_session, "newbie", "password123")
    await db_session.commit()
    return u


@pytest.fixture
async def board(db_session, sysop):
    b = await create_board(db_session, "General", actor=sysop, description="General chat")
    await db_session.commit()
    return b


@pytest.fixture
async def sysop_board(db_session, sysop):
    b = await create_board(
        db_session,
        "Sysop Lounge",
        actor=sysop,
        read_level=AccessLevel.SYSOP,
        post_level=AccessLevel.SYSOP,
    )
    await db_session.commit()
    return b


# ── Exception hierarchy ───────────────────────────────────────────────────────


class TestExceptions:
    def test_board_not_found_is_message_error(self):
        assert issubclass(BoardNotFound, MessageError)

    def test_message_not_found_is_message_error(self):
        assert issubclass(MessageNotFound, MessageError)

    def test_permission_denied_is_message_error(self):
        assert issubclass(PermissionDenied, MessageError)

    def test_board_name_taken_is_message_error(self):
        assert issubclass(BoardNameTaken, MessageError)


# ── create_board ──────────────────────────────────────────────────────────────


class TestCreateBoard:
    async def test_sysop_creates_board(self, db_session, sysop):
        b = await create_board(db_session, "Tech Talk", actor=sysop)
        assert b.id is not None
        assert b.name == "Tech Talk"
        assert b.is_active is True

    async def test_non_sysop_cannot_create(self, db_session, user):
        with pytest.raises(PermissionDenied):
            await create_board(db_session, "Rebels", actor=user)

    async def test_duplicate_name_raises(self, db_session, sysop, board):
        with pytest.raises(BoardNameTaken):
            await create_board(db_session, "General", actor=sysop)

    async def test_duplicate_name_case_insensitive(self, db_session, sysop, board):
        with pytest.raises(BoardNameTaken):
            await create_board(db_session, "GENERAL", actor=sysop)

    async def test_custom_levels(self, db_session, sysop):
        b = await create_board(
            db_session,
            "Sysop Only",
            actor=sysop,
            read_level=AccessLevel.SYSOP,
            post_level=AccessLevel.SYSOP,
        )
        assert b.read_level == AccessLevel.SYSOP
        assert b.post_level == AccessLevel.SYSOP

    async def test_whitespace_stripped_from_name(self, db_session, sysop):
        b = await create_board(db_session, "  Padded  ", actor=sysop)
        assert b.name == "Padded"

    async def test_description_stored(self, db_session, sysop):
        b = await create_board(db_session, "Described", actor=sysop, description="Nice board")
        assert b.description == "Nice board"


# ── list_boards ───────────────────────────────────────────────────────────────


class TestListBoards:
    async def test_user_sees_user_boards(self, db_session, user, board):
        boards = await list_boards(db_session, user)
        assert any(b.id == board.id for b in boards)

    async def test_user_cannot_see_sysop_board(self, db_session, user, sysop_board):
        boards = await list_boards(db_session, user)
        assert not any(b.id == sysop_board.id for b in boards)

    async def test_sysop_sees_all_boards(self, db_session, sysop, board, sysop_board):
        boards = await list_boards(db_session, sysop)
        ids = {b.id for b in boards}
        assert board.id in ids
        assert sysop_board.id in ids

    async def test_inactive_board_hidden(self, db_session, user, board):
        board.is_active = False
        await db_session.commit()
        boards = await list_boards(db_session, user)
        assert not any(b.id == board.id for b in boards)

    async def test_sorted_by_sort_order_then_name(self, db_session, sysop):
        b1 = await create_board(db_session, "Zzz", actor=sysop, sort_order=10)
        b2 = await create_board(db_session, "Aaa", actor=sysop, sort_order=5)
        await db_session.commit()
        boards = await list_boards(db_session, sysop)
        ids = [b.id for b in boards]
        assert ids.index(b2.id) < ids.index(b1.id)


# ── get_board ─────────────────────────────────────────────────────────────────


class TestGetBoard:
    async def test_returns_board(self, db_session, user, board):
        b = await get_board(db_session, board.id, user)
        assert b.id == board.id

    async def test_inactive_raises_not_found(self, db_session, user, board):
        board.is_active = False
        await db_session.commit()
        with pytest.raises(BoardNotFound):
            await get_board(db_session, board.id, user)

    async def test_missing_raises_not_found(self, db_session, user):
        with pytest.raises(BoardNotFound):
            await get_board(db_session, 9999, user)

    async def test_below_read_level_raises_permission(self, db_session, new_user, board):
        with pytest.raises(PermissionDenied):
            await get_board(db_session, board.id, new_user)


# ── update_board ──────────────────────────────────────────────────────────────


class TestUpdateBoard:
    async def test_rename_board(self, db_session, sysop, board):
        b = await update_board(db_session, board.id, actor=sysop, name="Renamed")
        assert b.name == "Renamed"

    async def test_deactivate_board(self, db_session, sysop, board):
        b = await update_board(db_session, board.id, actor=sysop, is_active=False)
        assert b.is_active is False

    async def test_duplicate_name_on_rename(self, db_session, sysop, board):
        await create_board(db_session, "Other", actor=sysop)
        await db_session.commit()
        with pytest.raises(BoardNameTaken):
            await update_board(db_session, board.id, actor=sysop, name="Other")

    async def test_same_name_allowed(self, db_session, sysop, board):
        b = await update_board(db_session, board.id, actor=sysop, name="General")
        assert b.name == "General"

    async def test_non_sysop_cannot_update(self, db_session, user, board):
        with pytest.raises(PermissionDenied):
            await update_board(db_session, board.id, actor=user, name="Hijacked")

    async def test_missing_board_raises(self, db_session, sysop):
        with pytest.raises(BoardNotFound):
            await update_board(db_session, 9999, actor=sysop, name="Ghost")


# ── post_message ──────────────────────────────────────────────────────────────


class TestPostMessage:
    async def test_post_creates_message(self, db_session, user, board):
        msg = await post_message(db_session, board.id, "Hello", "World", user)
        assert msg.id is not None
        assert msg.subject == "Hello"
        assert msg.body == "World"
        assert msg.author_id == user.id
        assert msg.reply_to_id is None

    async def test_post_increments_messages_posted(self, db_session, user, board):
        before = user.messages_posted
        await post_message(db_session, board.id, "S", "B", user)
        assert user.messages_posted == before + 1

    async def test_reply_links_parent(self, db_session, user, board):
        parent = await post_message(db_session, board.id, "Original", "Body", user)
        await db_session.commit()
        reply = await post_message(
            db_session, board.id, "Re: Original", "Reply", user, reply_to_id=parent.id
        )
        assert reply.reply_to_id == parent.id

    async def test_post_below_post_level_denied(self, db_session, new_user, board):
        with pytest.raises(PermissionDenied):
            await post_message(db_session, board.id, "S", "B", new_user)

    async def test_post_to_missing_board_raises(self, db_session, user):
        with pytest.raises(BoardNotFound):
            await post_message(db_session, 9999, "S", "B", user)

    async def test_empty_subject_raises(self, db_session, user, board):
        with pytest.raises(ValueError, match="Subject"):
            await post_message(db_session, board.id, "   ", "body", user)

    async def test_empty_body_raises(self, db_session, user, board):
        with pytest.raises(ValueError, match="Body"):
            await post_message(db_session, board.id, "Sub", "   ", user)

    async def test_reply_to_deleted_raises(self, db_session, user, board):
        parent = await post_message(db_session, board.id, "Sub", "Body", user)
        await db_session.commit()
        parent.is_deleted = True
        await db_session.commit()
        with pytest.raises(MessageNotFound):
            await post_message(db_session, board.id, "Re", "Reply", user, reply_to_id=parent.id)

    async def test_reply_to_wrong_board_raises(self, db_session, sysop, user, board):
        other = await create_board(db_session, "Other", actor=sysop)
        await db_session.commit()
        parent = await post_message(db_session, other.id, "Sub", "Body", sysop)
        await db_session.commit()
        with pytest.raises(MessageNotFound):
            await post_message(db_session, board.id, "Re", "Reply", user, reply_to_id=parent.id)


# ── list_thread_starters ──────────────────────────────────────────────────────


class TestListThreadStarters:
    async def test_returns_top_level_only(self, db_session, user, board):
        parent = await post_message(db_session, board.id, "Root", "Body", user)
        await db_session.commit()
        await post_message(db_session, board.id, "Reply", "Body", user, reply_to_id=parent.id)
        await db_session.commit()

        threads = await list_thread_starters(db_session, board.id, user)
        assert all(m.reply_to_id is None for m in threads)
        assert any(m.id == parent.id for m in threads)

    async def test_deleted_excluded(self, db_session, user, board):
        msg = await post_message(db_session, board.id, "Gone", "Body", user)
        await db_session.commit()
        msg.is_deleted = True
        await db_session.commit()
        threads = await list_thread_starters(db_session, board.id, user)
        assert not any(m.id == msg.id for m in threads)

    async def test_access_check(self, db_session, new_user, board):
        with pytest.raises(PermissionDenied):
            await list_thread_starters(db_session, board.id, new_user)

    async def test_limit_and_offset(self, db_session, user, board):
        for i in range(5):
            await post_message(db_session, board.id, f"Msg {i}", "Body", user)
        await db_session.commit()

        page1 = await list_thread_starters(db_session, board.id, user, limit=3, offset=0)
        page2 = await list_thread_starters(db_session, board.id, user, limit=3, offset=3)
        assert len(page1) == 3
        assert len(page2) == 2
        ids1 = {m.id for m in page1}
        ids2 = {m.id for m in page2}
        assert ids1.isdisjoint(ids2)


# ── get_thread ────────────────────────────────────────────────────────────────


class TestGetThread:
    async def test_returns_root_and_replies(self, db_session, user, board):
        root = await post_message(db_session, board.id, "Root", "Body", user)
        await db_session.commit()
        r1 = await post_message(db_session, board.id, "R1", "Body", user, reply_to_id=root.id)
        r2 = await post_message(db_session, board.id, "R2", "Body", user, reply_to_id=root.id)
        await db_session.commit()

        fetched_root, replies = await get_thread(db_session, root.id, user)
        assert fetched_root.id == root.id
        reply_ids = {m.id for m in replies}
        assert r1.id in reply_ids
        assert r2.id in reply_ids

    async def test_deleted_root_raises(self, db_session, user, board):
        msg = await post_message(db_session, board.id, "Sub", "Body", user)
        await db_session.commit()
        msg.is_deleted = True
        await db_session.commit()
        with pytest.raises(MessageNotFound):
            await get_thread(db_session, msg.id, user)

    async def test_deleted_replies_excluded(self, db_session, user, board):
        root = await post_message(db_session, board.id, "Root", "Body", user)
        await db_session.commit()
        reply = await post_message(db_session, board.id, "Reply", "Body", user, reply_to_id=root.id)
        await db_session.commit()
        reply.is_deleted = True
        await db_session.commit()

        _, replies = await get_thread(db_session, root.id, user)
        assert not any(m.id == reply.id for m in replies)

    async def test_access_check(self, db_session, sysop, new_user, board):
        root = await post_message(db_session, board.id, "Root", "Body", sysop)
        await db_session.commit()
        with pytest.raises(PermissionDenied):
            await get_thread(db_session, root.id, new_user)


# ── edit_message ──────────────────────────────────────────────────────────────


class TestEditMessage:
    async def test_author_can_edit(self, db_session, user, board):
        msg = await post_message(db_session, board.id, "Sub", "Original", user)
        await db_session.commit()
        edited = await edit_message(db_session, msg.id, actor=user, body="Updated")
        assert edited.body == "Updated"
        assert edited.edited_at is not None

    async def test_sysop_can_edit_any(self, db_session, sysop, user, board):
        msg = await post_message(db_session, board.id, "Sub", "Body", user)
        await db_session.commit()
        edited = await edit_message(db_session, msg.id, actor=sysop, body="Fixed")
        assert edited.body == "Fixed"

    async def test_other_user_cannot_edit(self, db_session, user, board, db_session_user2):
        msg = await post_message(db_session, board.id, "Sub", "Body", user)
        await db_session.commit()
        with pytest.raises(PermissionDenied):
            await edit_message(db_session, msg.id, actor=db_session_user2, body="Hack")

    async def test_deleted_message_raises(self, db_session, user, board):
        msg = await post_message(db_session, board.id, "Sub", "Body", user)
        await db_session.commit()
        msg.is_deleted = True
        await db_session.commit()
        with pytest.raises(MessageNotFound):
            await edit_message(db_session, msg.id, actor=user, body="Ghost")

    async def test_empty_body_raises(self, db_session, user, board):
        msg = await post_message(db_session, board.id, "Sub", "Body", user)
        await db_session.commit()
        with pytest.raises(ValueError, match="Body"):
            await edit_message(db_session, msg.id, actor=user, body="  ")


# ── delete_message ────────────────────────────────────────────────────────────


class TestDeleteMessage:
    async def test_author_can_delete(self, db_session, user, board):
        msg = await post_message(db_session, board.id, "Sub", "Body", user)
        await db_session.commit()
        deleted = await delete_message(db_session, msg.id, actor=user)
        assert deleted.is_deleted is True

    async def test_sysop_can_delete_any(self, db_session, sysop, user, board):
        msg = await post_message(db_session, board.id, "Sub", "Body", user)
        await db_session.commit()
        deleted = await delete_message(db_session, msg.id, actor=sysop)
        assert deleted.is_deleted is True

    async def test_other_user_cannot_delete(self, db_session, user, board, db_session_user2):
        msg = await post_message(db_session, board.id, "Sub", "Body", user)
        await db_session.commit()
        with pytest.raises(PermissionDenied):
            await delete_message(db_session, msg.id, actor=db_session_user2)

    async def test_already_deleted_raises(self, db_session, user, board):
        msg = await post_message(db_session, board.id, "Sub", "Body", user)
        await db_session.commit()
        await delete_message(db_session, msg.id, actor=user)
        await db_session.commit()
        with pytest.raises(MessageNotFound):
            await delete_message(db_session, msg.id, actor=user)

    async def test_missing_message_raises(self, db_session, user):
        with pytest.raises(MessageNotFound):
            await delete_message(db_session, 9999, actor=user)


# ── message_count ─────────────────────────────────────────────────────────────


class TestMessageCount:
    async def test_counts_active_messages(self, db_session, user, board):
        assert await message_count(db_session, board.id) == 0
        await post_message(db_session, board.id, "S1", "B1", user)
        await post_message(db_session, board.id, "S2", "B2", user)
        await db_session.commit()
        assert await message_count(db_session, board.id) == 2

    async def test_excludes_deleted_by_default(self, db_session, user, board):
        msg = await post_message(db_session, board.id, "S", "B", user)
        await db_session.commit()
        msg.is_deleted = True
        await db_session.commit()
        assert await message_count(db_session, board.id) == 0

    async def test_include_deleted_flag(self, db_session, user, board):
        msg = await post_message(db_session, board.id, "S", "B", user)
        await db_session.commit()
        msg.is_deleted = True
        await db_session.commit()
        assert await message_count(db_session, board.id, include_deleted=True) == 1


# ── Helper fixture for a second regular user ─────────────────────────────────


@pytest.fixture
async def db_session_user2(db_session, sysop):
    u = await signup(db_session, "otherguy", "password456")
    u.access_level = AccessLevel.USER
    await db_session.commit()
    return u
