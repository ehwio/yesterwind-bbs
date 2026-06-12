"""
ORM models (SQLAlchemy 2.0 declarative style).

Access levels follow the classic BBS integer convention:
  NEW    =   0   newly registered, awaiting validation
  USER   =  10   validated regular user
  SYSOP  = 200   sysop — full access

Sysops can set custom thresholds; store the integer and compare with >=.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Access level constants ─────────────────────────────────────────────────────


class AccessLevel:
    NEW = 0  # new user, unvalidated
    USER = 10  # regular validated user
    SYSOP = 200  # sysop


# ── Terminal type (mirrors terminal.base.TerminalType) ─────────────────────────


class TerminalPreference(enum.Enum):
    ANSI = "ansi"
    ATASCII = "atascii"
    PETSCII = "petscii"
    ASCII = "ascii"


# ── Base ───────────────────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    pass


# ── Users ──────────────────────────────────────────────────────────────────────


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Identity
    username: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str | None] = mapped_column(String(254), unique=True, nullable=True)
    real_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    location: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Access
    access_level: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=AccessLevel.NEW)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Terminal preferences
    terminal: Mapped[str] = mapped_column(
        String(16), nullable=False, default=TerminalPreference.ANSI.value
    )
    screen_width: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=80)
    screen_lines: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=24)

    # Time limits (minutes per day; 0 = unlimited)
    time_limit: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    # Statistics
    login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    messages_posted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    files_uploaded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    files_downloaded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bytes_uploaded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bytes_downloaded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    messages: Mapped[list[Message]] = relationship(
        "Message", back_populates="author", lazy="select"
    )
    uploads: Mapped[list[FileEntry]] = relationship(
        "FileEntry", back_populates="uploader", lazy="select"
    )
    sessions: Mapped[list[Session]] = relationship("Session", back_populates="user", lazy="select")

    def __repr__(self) -> str:
        return f"<User {self.username!r} level={self.access_level}>"

    @property
    def is_sysop(self) -> bool:
        return self.access_level >= AccessLevel.SYSOP

    @property
    def is_validated(self) -> bool:
        return self.access_level >= AccessLevel.USER


# ── Message boards & messages ─────────────────────────────────────────────────


class MessageBoard(Base):
    __tablename__ = "message_boards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Minimum access level required to read / post
    read_level: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=AccessLevel.USER)
    post_level: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=AccessLevel.USER)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    messages: Mapped[list[Message]] = relationship("Message", back_populates="board", lazy="select")

    def __repr__(self) -> str:
        return f"<MessageBoard {self.name!r}>"


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    board_id: Mapped[int] = mapped_column(Integer, ForeignKey("message_boards.id"), nullable=False)
    author_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)

    subject: Mapped[str] = mapped_column(String(128), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    reply_to_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("messages.id"), nullable=True
    )

    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    board: Mapped[MessageBoard] = relationship("MessageBoard", back_populates="messages")
    author: Mapped[User] = relationship("User", back_populates="messages")
    replies: Mapped[list[Message]] = relationship("Message", back_populates="parent", lazy="select")
    parent: Mapped[Message | None] = relationship(
        "Message", back_populates="replies", remote_side="Message.id"
    )

    def __repr__(self) -> str:
        return f"<Message {self.id} {self.subject!r}>"


# ── File areas & files ────────────────────────────────────────────────────────


class FileArea(Base):
    __tablename__ = "file_areas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Subdirectory path relative to the data/files/ root
    path: Mapped[str] = mapped_column(String(255), nullable=False)

    # Minimum access level required to browse / upload
    read_level: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=AccessLevel.USER)
    upload_level: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=AccessLevel.USER
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    files: Mapped[list[FileEntry]] = relationship("FileEntry", back_populates="area", lazy="select")

    def __repr__(self) -> str:
        return f"<FileArea {self.name!r}>"


class FileEntry(Base):
    __tablename__ = "file_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    area_id: Mapped[int] = mapped_column(Integer, ForeignKey("file_areas.id"), nullable=False)
    uploader_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,  # nullable for sysop imports
    )

    # Stored filename on disk (UUID-based to avoid collisions)
    stored_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    # Original filename shown to users
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)

    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    download_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    # Relationships
    area: Mapped[FileArea] = relationship("FileArea", back_populates="files")
    uploader: Mapped[User | None] = relationship("User", back_populates="uploads")

    def __repr__(self) -> str:
        return f"<FileEntry {self.display_name!r} ({self.size_bytes} bytes)>"

    __table_args__ = (
        UniqueConstraint("area_id", "display_name", name="uq_file_area_display_name"),
    )


# ── Active sessions (node tracking) ───────────────────────────────────────────


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,  # null before login
    )
    remote_addr: Mapped[str] = mapped_column(String(45), nullable=False)  # fits IPv6
    node_number: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    terminal: Mapped[str] = mapped_column(String(16), nullable=False, default="ansi")

    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User | None] = relationship("User", back_populates="sessions")

    def __repr__(self) -> str:
        return f"<Session node={self.node_number} user={self.user_id} from={self.remote_addr}>"
