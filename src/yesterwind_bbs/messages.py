"""
Message board CRUD — list boards, read threads, post and edit messages.

Access control mirrors the classic BBS convention:
  - read_level  : minimum access_level to list/read a board
  - post_level  : minimum access_level to post or reply
  - Sysops may edit or delete any message; authors may edit their own.
  - Deletion is soft (is_deleted flag); the row is never removed.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yesterwind_bbs.db.models import AccessLevel, Message, MessageBoard, User

# ── Exceptions ────────────────────────────────────────────────────────────────


class MessageError(Exception):
    """Base class for all message-layer errors."""


class BoardNotFound(MessageError):
    """Raised when a requested board does not exist or is inactive."""


class MessageNotFound(MessageError):
    """Raised when a requested message does not exist or has been deleted."""


class PermissionDenied(MessageError):
    """Raised when the caller lacks sufficient access for the operation."""


class BoardNameTaken(MessageError):
    """Raised when a board with that name already exists."""


# ── Board operations ──────────────────────────────────────────────────────────


async def list_boards(
    session: AsyncSession,
    actor: User,
) -> list[MessageBoard]:
    """Return all active boards the actor has at least read access to."""
    result = await session.execute(
        select(MessageBoard)
        .where(
            MessageBoard.is_active == True,  # noqa: E712
            MessageBoard.read_level <= actor.access_level,
        )
        .order_by(MessageBoard.sort_order, MessageBoard.name)
    )
    return list(result.scalars().all())


async def get_board(
    session: AsyncSession,
    board_id: int,
    actor: User,
) -> MessageBoard:
    """
    Fetch a single active board by id.

    Raises:
        BoardNotFound   — board doesn't exist or is inactive
        PermissionDenied — actor is below read_level
    """
    result = await session.execute(
        select(MessageBoard).where(MessageBoard.id == board_id)
    )
    board = result.scalar_one_or_none()
    if board is None or not board.is_active:
        raise BoardNotFound(f"Board {board_id} not found.")
    if actor.access_level < board.read_level:
        raise PermissionDenied("You do not have access to this board.")
    return board


async def create_board(
    session: AsyncSession,
    name: str,
    *,
    actor: User,
    description: str | None = None,
    read_level: int = AccessLevel.USER,
    post_level: int = AccessLevel.USER,
    sort_order: int = 0,
) -> MessageBoard:
    """
    Create a new message board. Only sysops may create boards.

    Raises:
        PermissionDenied — actor is not a sysop
        BoardNameTaken   — a board with that name already exists
    """
    if not actor.is_sysop:
        raise PermissionDenied("Only sysops can create boards.")

    name = name.strip()
    existing = await session.execute(
        select(MessageBoard).where(func.lower(MessageBoard.name) == name.lower())
    )
    if existing.scalar_one_or_none() is not None:
        raise BoardNameTaken(f"A board named '{name}' already exists.")

    board = MessageBoard(
        name=name,
        description=description,
        read_level=read_level,
        post_level=post_level,
        sort_order=sort_order,
    )
    session.add(board)
    await session.flush()
    return board


async def update_board(
    session: AsyncSession,
    board_id: int,
    *,
    actor: User,
    name: str | None = None,
    description: str | None = None,
    read_level: int | None = None,
    post_level: int | None = None,
    sort_order: int | None = None,
    is_active: bool | None = None,
) -> MessageBoard:
    """
    Update board metadata. Only sysops may update boards.

    Raises:
        PermissionDenied — actor is not a sysop
        BoardNotFound    — board doesn't exist
        BoardNameTaken   — new name conflicts with existing board
    """
    if not actor.is_sysop:
        raise PermissionDenied("Only sysops can update boards.")

    result = await session.execute(
        select(MessageBoard).where(MessageBoard.id == board_id)
    )
    board = result.scalar_one_or_none()
    if board is None:
        raise BoardNotFound(f"Board {board_id} not found.")

    if name is not None:
        name = name.strip()
        conflict = await session.execute(
            select(MessageBoard).where(
                func.lower(MessageBoard.name) == name.lower(),
                MessageBoard.id != board_id,
            )
        )
        if conflict.scalar_one_or_none() is not None:
            raise BoardNameTaken(f"A board named '{name}' already exists.")
        board.name = name

    if description is not None:
        board.description = description
    if read_level is not None:
        board.read_level = read_level
    if post_level is not None:
        board.post_level = post_level
    if sort_order is not None:
        board.sort_order = sort_order
    if is_active is not None:
        board.is_active = is_active

    await session.flush()
    return board


# ── Message listing ───────────────────────────────────────────────────────────


async def list_thread_starters(
    session: AsyncSession,
    board_id: int,
    actor: User,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[Message]:
    """
    Return top-level (non-reply) messages in a board, newest first.
    Soft-deleted messages are excluded.

    Raises:
        BoardNotFound    — board doesn't exist or is inactive
        PermissionDenied — actor below read_level
    """
    await get_board(session, board_id, actor)  # access check

    result = await session.execute(
        select(Message)
        .where(
            Message.board_id == board_id,
            Message.reply_to_id == None,  # noqa: E711
            Message.is_deleted == False,  # noqa: E712
        )
        .order_by(Message.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def get_thread(
    session: AsyncSession,
    message_id: int,
    actor: User,
) -> tuple[Message, list[Message]]:
    """
    Return the root message and its direct replies (not soft-deleted).

    Raises:
        MessageNotFound  — root message not found or deleted
        BoardNotFound    — board is inactive
        PermissionDenied — actor below board's read_level
    """
    result = await session.execute(
        select(Message).where(Message.id == message_id)
    )
    root = result.scalar_one_or_none()
    if root is None or root.is_deleted:
        raise MessageNotFound(f"Message {message_id} not found.")

    await get_board(session, root.board_id, actor)  # access check

    replies_result = await session.execute(
        select(Message)
        .where(
            Message.reply_to_id == message_id,
            Message.is_deleted == False,  # noqa: E712
        )
        .order_by(Message.created_at.asc())
    )
    return root, list(replies_result.scalars().all())


# ── Posting ───────────────────────────────────────────────────────────────────


async def post_message(
    session: AsyncSession,
    board_id: int,
    subject: str,
    body: str,
    actor: User,
    *,
    reply_to_id: int | None = None,
) -> Message:
    """
    Post a new message (or reply) to a board.

    Raises:
        BoardNotFound    — board doesn't exist or is inactive
        PermissionDenied — actor below post_level
        MessageNotFound  — reply_to_id specified but not found / deleted
    """
    board = await get_board(session, board_id, actor)

    if actor.access_level < board.post_level:
        raise PermissionDenied("You do not have permission to post to this board.")

    subject = subject.strip()
    if not subject:
        raise ValueError("Subject must not be empty.")
    if not body.strip():
        raise ValueError("Body must not be empty.")

    if reply_to_id is not None:
        result = await session.execute(
            select(Message).where(Message.id == reply_to_id)
        )
        parent = result.scalar_one_or_none()
        if parent is None or parent.is_deleted:
            raise MessageNotFound(f"Message {reply_to_id} not found.")
        if parent.board_id != board_id:
            raise MessageNotFound("Reply target is not in this board.")

    msg = Message(
        board_id=board_id,
        author_id=actor.id,
        subject=subject,
        body=body,
        reply_to_id=reply_to_id,
    )
    session.add(msg)
    actor.messages_posted += 1
    await session.flush()
    return msg


# ── Editing & deletion ────────────────────────────────────────────────────────


async def edit_message(
    session: AsyncSession,
    message_id: int,
    *,
    actor: User,
    body: str,
) -> Message:
    """
    Edit a message body. Authors may edit their own; sysops may edit any.

    Raises:
        MessageNotFound  — message not found or deleted
        PermissionDenied — actor is neither the author nor a sysop
    """
    result = await session.execute(
        select(Message).where(Message.id == message_id)
    )
    msg = result.scalar_one_or_none()
    if msg is None or msg.is_deleted:
        raise MessageNotFound(f"Message {message_id} not found.")

    if msg.author_id != actor.id and not actor.is_sysop:
        raise PermissionDenied("You can only edit your own messages.")

    if not body.strip():
        raise ValueError("Body must not be empty.")

    msg.body = body
    msg.edited_at = datetime.now(timezone.utc)
    await session.flush()
    return msg


async def delete_message(
    session: AsyncSession,
    message_id: int,
    *,
    actor: User,
) -> Message:
    """
    Soft-delete a message. Authors may delete their own; sysops may delete any.

    Raises:
        MessageNotFound  — message not found or already deleted
        PermissionDenied — actor is neither the author nor a sysop
    """
    result = await session.execute(
        select(Message).where(Message.id == message_id)
    )
    msg = result.scalar_one_or_none()
    if msg is None or msg.is_deleted:
        raise MessageNotFound(f"Message {message_id} not found.")

    if msg.author_id != actor.id and not actor.is_sysop:
        raise PermissionDenied("You can only delete your own messages.")

    msg.is_deleted = True
    await session.flush()
    return msg


# ── Sysop convenience ─────────────────────────────────────────────────────────


async def message_count(
    session: AsyncSession,
    board_id: int,
    *,
    include_deleted: bool = False,
) -> int:
    """Return the number of messages in a board."""
    conditions = [Message.board_id == board_id]
    if not include_deleted:
        conditions.append(Message.is_deleted == False)  # noqa: E712
    result = await session.execute(
        select(func.count()).select_from(Message).where(*conditions)
    )
    return result.scalar_one()
