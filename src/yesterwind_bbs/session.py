"""
Per-connection session — terminal handshake, login/signup, and main menu.

State machine
─────────────
  CONNECT → terminal negotiation
          → LOGIN (up to 3 attempts)
               → bad creds  → DISCONNECT
               → inactive   → DISCONNECT
               → new user   → SIGNUP path
               → ok         → MAIN_MENU
          → MAIN_MENU
               → [B] boards → BOARDS_MENU
               → [F] files  → FILES_MENU
               → [G] goodbye → DISCONNECT

All I/O goes through the Terminal codec so ANSI, ATASCII, PETSCII, and
plain ASCII callers each get appropriate byte sequences.  A session row
is created immediately on connection and updated throughout.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from yesterwind_bbs import config, telnet
from yesterwind_bbs.auth import (
    AuthError,
    InvalidCredentials,
    UserInactive,
    login,
    signup,
    validate_password,
    validate_username,
)
from yesterwind_bbs.db.engine import get_session
from yesterwind_bbs.db.models import AccessLevel, User
from yesterwind_bbs.db.models import Session as BbsSession
from yesterwind_bbs.files import (
    FileError,
    FileNotFound,
    list_areas,
    list_files,
    send_file_xyzmodem,
)
from yesterwind_bbs.files import (
    PermissionDenied as FilePermissionDenied,
)
from yesterwind_bbs.messages import (
    MessageError,
    get_thread,
    list_boards,
    list_thread_starters,
    post_message,
)
from yesterwind_bbs.messages import (
    PermissionDenied as MsgPermissionDenied,
)
from yesterwind_bbs.terminal.ansi import AnsiTerminal
from yesterwind_bbs.terminal.ascii import AsciiTerminal
from yesterwind_bbs.terminal.atascii import AtasciiTerminal
from yesterwind_bbs.terminal.base import TERMINAL_MENU, Terminal, TerminalType
from yesterwind_bbs.terminal.petscii import PetsciiTerminal

log = logging.getLogger(__name__)

_TERMINAL_MAP: dict[TerminalType, type[Terminal]] = {
    TerminalType.ANSI: AnsiTerminal,
    TerminalType.ATASCII: AtasciiTerminal,
    TerminalType.PETSCII: PetsciiTerminal,
    TerminalType.ASCII: AsciiTerminal,
}

_MENU_TIMEOUT = 120.0  # seconds waiting for a menu keypress
_LOGIN_TIMEOUT = 60.0  # seconds for username/password entry
_MAX_LOGIN_ATTEMPTS = 3


# ── Low-level I/O helpers ─────────────────────────────────────────────────────


class _Conn:
    """Thin wrapper around (reader, writer) with terminal-aware send helpers."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        term: Terminal,
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.term = term

    async def send(self, text: str) -> None:
        self.writer.write(self.term.encode(text))
        await self.writer.drain()

    async def sendline(self, text: str = "") -> None:
        self.writer.write(self.term.write(text))
        await self.writer.drain()

    async def clear(self) -> None:
        self.writer.write(self.term.clear_screen())
        await self.writer.drain()

    async def read_line(self, *, timeout: float = _LOGIN_TIMEOUT, echo: bool = True) -> str:
        """
        Read characters until ENTER, with backspace support.
        Returns the stripped line.  Raises asyncio.TimeoutError on timeout.
        """
        buf: list[str] = []
        while True:
            raw = await asyncio.wait_for(self.reader.read(1), timeout=timeout)
            if not raw:
                raise ConnectionResetError("Client disconnected")
            key = self.term.decode_key(raw)
            if key == "ENTER":
                await self.sendline()
                return "".join(buf).strip()
            elif key == "BACKSPACE":
                if buf:
                    buf.pop()
                    if echo:
                        self.writer.write(b"\x08 \x08")
                        await self.writer.drain()
            elif len(key) == 1:
                buf.append(key)
                if echo:
                    await self.send(key)

    async def read_key(self, *, timeout: float = _MENU_TIMEOUT) -> str:
        """Read a single keypress.  Raises asyncio.TimeoutError on timeout."""
        while True:
            raw = await asyncio.wait_for(self.reader.read(3), timeout=timeout)
            if not raw:
                raise ConnectionResetError("Client disconnected")
            key = self.term.decode_key(raw)
            if key:
                return key

    async def hr(self) -> None:
        """Print a horizontal divider appropriate for the terminal."""
        await self.sendline("-" * 60)

    async def banner(self) -> None:
        await self.clear()
        await self.sendline()
        await self.sendline(f"  {config.BBS_NAME}")
        await self.sendline(f"  Sysop: {config.BBS_SYSOP}")
        await self.hr()


# ── Session row tracking ──────────────────────────────────────────────────────


async def _create_session_row(remote_addr: str, terminal_name: str) -> int:
    async with get_session() as session:
        row = BbsSession(remote_addr=remote_addr, terminal=terminal_name)
        session.add(row)
        await session.flush()
        return row.id


async def _update_session_user(session_id: int, user_id: int) -> None:
    from sqlalchemy import select

    async with get_session() as session:
        result = await session.execute(select(BbsSession).where(BbsSession.id == session_id))
        row = result.scalar_one_or_none()
        if row:
            row.user_id = user_id


async def _close_session_row(session_id: int) -> None:
    from sqlalchemy import select

    async with get_session() as session:
        result = await session.execute(select(BbsSession).where(BbsSession.id == session_id))
        row = result.scalar_one_or_none()
        if row:
            row.disconnected_at = datetime.now(timezone.utc)


async def _touch_session(session_id: int) -> None:
    from sqlalchemy import select

    async with get_session() as session:
        result = await session.execute(select(BbsSession).where(BbsSession.id == session_id))
        row = result.scalar_one_or_none()
        if row:
            row.last_activity_at = datetime.now(timezone.utc)


# ── Terminal negotiation ──────────────────────────────────────────────────────


async def _negotiate_terminal(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> Terminal:
    ttype_str = await telnet.passive_detect(reader)
    if ttype_str:
        detected = TerminalType.from_ttype(ttype_str)
        if detected:
            log.debug("Auto-detected terminal: %s (%s)", detected.name, ttype_str)
            return _TERMINAL_MAP[detected]()

    writer.write(TERMINAL_MENU)
    await writer.drain()

    while True:
        try:
            data = await asyncio.wait_for(reader.read(1), timeout=_MENU_TIMEOUT)
        except asyncio.TimeoutError:
            writer.write(b"\r\nTimed out.\r\n")
            await writer.drain()
            raise

        if not data:
            raise ConnectionResetError("Client disconnected during terminal selection")

        choice = data.decode("ascii", errors="replace").strip()
        term_type = TerminalType.from_choice(choice)
        if term_type:
            return _TERMINAL_MAP[term_type]()

        writer.write(b"Invalid choice. Enter 1, 2, 3, or 4: ")
        await writer.drain()


# ── Login / signup ────────────────────────────────────────────────────────────


async def _login_screen(conn: _Conn) -> User | None:
    """
    Prompt for credentials.  Returns the authenticated User, or None if the
    caller exhausts all attempts or disconnects.
    """
    for attempt in range(_MAX_LOGIN_ATTEMPTS):
        await conn.sendline()
        await conn.send("Username: ")
        try:
            username = await conn.read_line(timeout=_LOGIN_TIMEOUT)
        except asyncio.TimeoutError:
            await conn.sendline("Timed out.")
            return None

        if not username:
            continue

        # NEW prompt offers signup path
        if username.upper() == "NEW":
            return await _signup_screen(conn)

        await conn.send("Password: ")
        try:
            password = await conn.read_line(timeout=_LOGIN_TIMEOUT, echo=False)
        except asyncio.TimeoutError:
            await conn.sendline("Timed out.")
            return None

        try:
            async with get_session() as session:
                user = await login(session, username, password)
            await conn.sendline(f"Welcome back, {user.username}!")
            return user
        except InvalidCredentials:
            remaining = _MAX_LOGIN_ATTEMPTS - attempt - 1
            await conn.sendline(f"Invalid login. {remaining} attempt(s) remaining.")
        except UserInactive:
            await conn.sendline("That account has been disabled.")
            return None
        except AuthError as exc:
            await conn.sendline(str(exc))
            return None

    await conn.sendline("Too many failed attempts. Goodbye.")
    return None


async def _signup_screen(conn: _Conn) -> User | None:
    """Walk a new caller through account creation."""
    await conn.sendline()
    await conn.sendline("=== New User Signup ===")
    await conn.sendline("(Enter a blank line at any prompt to cancel)")
    await conn.sendline()

    # Username
    await conn.send("Desired username: ")
    try:
        username = await conn.read_line(timeout=_LOGIN_TIMEOUT)
    except asyncio.TimeoutError:
        await conn.sendline("Timed out.")
        return None
    if not username:
        await conn.sendline("Signup cancelled.")
        return None
    try:
        validate_username(username)
    except AuthError as exc:
        await conn.sendline(str(exc))
        return None

    # Password
    await conn.send("Password (min 6 chars): ")
    try:
        password = await conn.read_line(timeout=_LOGIN_TIMEOUT, echo=False)
    except asyncio.TimeoutError:
        await conn.sendline("Timed out.")
        return None
    if not password:
        await conn.sendline("Signup cancelled.")
        return None
    try:
        validate_password(password)
    except AuthError as exc:
        await conn.sendline(str(exc))
        return None

    # Confirm password
    await conn.send("Confirm password: ")
    try:
        confirm = await conn.read_line(timeout=_LOGIN_TIMEOUT, echo=False)
    except asyncio.TimeoutError:
        await conn.sendline("Timed out.")
        return None
    if confirm != password:
        await conn.sendline("Passwords do not match.")
        return None

    # Optional fields
    await conn.send("Real name (optional): ")
    try:
        real_name = await conn.read_line(timeout=_LOGIN_TIMEOUT) or None
    except asyncio.TimeoutError:
        real_name = None

    await conn.send("Location (optional): ")
    try:
        location = await conn.read_line(timeout=_LOGIN_TIMEOUT) or None
    except asyncio.TimeoutError:
        location = None

    try:
        async with get_session() as session:
            user = await signup(session, username, password, real_name=real_name, location=location)
    except AuthError as exc:
        await conn.sendline(str(exc))
        return None

    if user.is_sysop:
        await conn.sendline(f"Welcome, {user.username}! First user — SYSOP access granted.")
    else:
        await conn.sendline(f"Welcome, {user.username}! Your account is pending validation.")
    return user


# ── Boards menu ───────────────────────────────────────────────────────────────


async def _boards_menu(conn: _Conn, user: User, session_id: int) -> None:
    while True:
        await _touch_session(session_id)
        await conn.sendline()
        await conn.sendline("=== Message Boards ===")

        async with get_session() as session:
            boards = await list_boards(session, user)

        if not boards:
            await conn.sendline("No message boards available.")
            await conn.sendline("[ENTER] Back")
            await conn.read_key()
            return

        for i, b in enumerate(boards, 1):
            desc = f"  - {b.description}" if b.description else ""
            await conn.sendline(f"  [{i}] {b.name}{desc}")
        await conn.sendline()
        await conn.send("Board number (or ENTER to go back): ")

        try:
            raw = await conn.read_line(timeout=_MENU_TIMEOUT)
        except asyncio.TimeoutError:
            return

        if not raw:
            return

        try:
            idx = int(raw) - 1
            if not (0 <= idx < len(boards)):
                raise ValueError
        except ValueError:
            await conn.sendline("Invalid selection.")
            continue

        await _board_view(conn, user, boards[idx], session_id)


async def _board_view(conn: _Conn, user: User, board, session_id: int) -> None:
    page_offset = 0
    page_size = 20

    while True:
        await _touch_session(session_id)
        await conn.sendline()
        await conn.sendline(f"=== {board.name} ===")
        if board.description:
            await conn.sendline(board.description)
        await conn.hr()

        try:
            async with get_session() as session:
                messages = await list_thread_starters(
                    session, board.id, user, limit=page_size, offset=page_offset
                )
        except (MessageError, MsgPermissionDenied) as exc:
            await conn.sendline(str(exc))
            return

        if not messages:
            await conn.sendline("No messages.")
        else:
            for i, msg in enumerate(messages, page_offset + 1):
                await conn.sendline(f"  [{i:3d}] {msg.subject[:50]}")

        await conn.sendline()
        await conn.sendline("[N]ext page  [P]rev page  [R]ead #  [W]rite  [B]ack")
        await conn.send("Choice: ")

        try:
            key = (await conn.read_line(timeout=_MENU_TIMEOUT)).upper()
        except asyncio.TimeoutError:
            return

        if key == "B" or key == "":
            return
        elif key == "N":
            page_offset += page_size
        elif key == "P":
            page_offset = max(0, page_offset - page_size)
        elif key == "W":
            await _write_message(conn, user, board.id, session_id)
        elif key.isdigit():
            idx = int(key) - 1 - page_offset
            if 0 <= idx < len(messages):
                await _read_thread(conn, user, messages[idx], session_id)
            else:
                await conn.sendline("Invalid message number.")
        elif key.startswith("R") and len(key) > 1 and key[1:].isdigit():
            num = int(key[1:]) - 1 - page_offset
            if 0 <= num < len(messages):
                await _read_thread(conn, user, messages[num], session_id)
            else:
                await conn.sendline("Invalid message number.")


async def _read_thread(conn: _Conn, user: User, root_msg, session_id: int) -> None:
    await _touch_session(session_id)
    try:
        async with get_session() as session:
            root, replies = await get_thread(session, root_msg.id, user)
    except MessageError as exc:
        await conn.sendline(str(exc))
        return

    await conn.sendline()
    await conn.hr()
    await conn.sendline(f"From: {root_msg.author_id}   Subject: {root.subject}")
    await conn.hr()
    await conn.sendline(root.body)

    for reply in replies:
        await conn.sendline()
        await conn.sendline("  --- Reply ---")
        await conn.sendline(f"  {reply.body}")

    await conn.sendline()
    await conn.sendline("[R]eply  [ENTER] Back")
    await conn.send("Choice: ")

    try:
        key = (await conn.read_line(timeout=_MENU_TIMEOUT)).upper()
    except asyncio.TimeoutError:
        return

    if key == "R":
        await _write_message(conn, user, root.board_id, session_id, reply_to_id=root.id)


async def _write_message(
    conn: _Conn, user: User, board_id: int, session_id: int, *, reply_to_id: int | None = None
) -> None:
    await _touch_session(session_id)

    if user.access_level < AccessLevel.USER:
        await conn.sendline("Your account must be validated before you can post.")
        return

    await conn.sendline()
    await conn.send("Subject: ")
    try:
        subject = await conn.read_line(timeout=_LOGIN_TIMEOUT)
    except asyncio.TimeoutError:
        return
    if not subject:
        await conn.sendline("Cancelled.")
        return

    await conn.sendline("Body (end with a line containing only a dot '.'):")
    lines: list[str] = []
    while True:
        try:
            line = await conn.read_line(timeout=_LOGIN_TIMEOUT)
        except asyncio.TimeoutError:
            await conn.sendline("Timed out.")
            return
        if line == ".":
            break
        lines.append(line)

    body = "\n".join(lines).strip()
    if not body:
        await conn.sendline("Cancelled — empty message.")
        return

    try:
        async with get_session() as session:
            await post_message(session, board_id, subject, body, user, reply_to_id=reply_to_id)
        await conn.sendline("Message posted.")
    except MessageError as exc:
        await conn.sendline(str(exc))


# ── Files menu ────────────────────────────────────────────────────────────────


async def _files_menu(conn: _Conn, user: User, session_id: int) -> None:
    while True:
        await _touch_session(session_id)
        await conn.sendline()
        await conn.sendline("=== File Areas ===")

        async with get_session() as session:
            areas = await list_areas(session, user)

        if not areas:
            await conn.sendline("No file areas available.")
            await conn.sendline("[ENTER] Back")
            await conn.read_key()
            return

        for i, a in enumerate(areas, 1):
            desc = f"  - {a.description}" if a.description else ""
            await conn.sendline(f"  [{i}] {a.name}{desc}")
        await conn.sendline()
        await conn.send("Area number (or ENTER to go back): ")

        try:
            raw = await conn.read_line(timeout=_MENU_TIMEOUT)
        except asyncio.TimeoutError:
            return

        if not raw:
            return

        try:
            idx = int(raw) - 1
            if not (0 <= idx < len(areas)):
                raise ValueError
        except ValueError:
            await conn.sendline("Invalid selection.")
            continue

        await _area_view(conn, user, areas[idx], session_id)


async def _area_view(conn: _Conn, user: User, area, session_id: int) -> None:
    page_offset = 0
    page_size = 20

    while True:
        await _touch_session(session_id)
        await conn.sendline()
        await conn.sendline(f"=== {area.name} ===")
        if area.description:
            await conn.sendline(area.description)
        await conn.hr()

        try:
            async with get_session() as session:
                files = await list_files(
                    session, area.id, user, limit=page_size, offset=page_offset
                )
        except (FileError, FilePermissionDenied) as exc:
            await conn.sendline(str(exc))
            return

        if not files:
            await conn.sendline("No files.")
        else:
            for i, f in enumerate(files, page_offset + 1):
                size_kb = f.size_bytes // 1024
                await conn.sendline(f"  [{i:3d}] {f.display_name:<30} {size_kb:>6} KB")
                if f.description:
                    await conn.sendline(f"         {f.description}")

        await conn.sendline()
        await conn.sendline("[N]ext  [P]rev  [D]ownload #  [B]ack")
        await conn.send("Choice: ")

        try:
            key = (await conn.read_line(timeout=_MENU_TIMEOUT)).upper()
        except asyncio.TimeoutError:
            return

        if key == "B" or key == "":
            return
        elif key == "N":
            page_offset += page_size
        elif key == "P":
            page_offset = max(0, page_offset - page_size)
        elif key.startswith("D") and len(key) > 1 and key[1:].isdigit():
            num = int(key[1:]) - 1 - page_offset
            if 0 <= num < len(files):
                await _download_file(conn, user, files[num], session_id)
            else:
                await conn.sendline("Invalid file number.")
        elif key.isdigit():
            num = int(key) - 1 - page_offset
            if 0 <= num < len(files):
                await _download_file(conn, user, files[num], session_id)
            else:
                await conn.sendline("Invalid file number.")


async def _download_file(conn: _Conn, user: User, file_entry, session_id: int) -> None:
    await _touch_session(session_id)
    await conn.sendline()
    await conn.sendline(f"File: {file_entry.display_name}  ({file_entry.size_bytes} bytes)")
    await conn.sendline("Protocol: [Z]modem  [Y]modem  [X]modem  [C]ancel")
    await conn.send("Choice: ")

    try:
        key = (await conn.read_line(timeout=_MENU_TIMEOUT)).upper()
    except asyncio.TimeoutError:
        return

    proto_map = {"Z": "zmodem", "Y": "ymodem", "X": "xmodem"}
    proto = proto_map.get(key)
    if proto is None:
        await conn.sendline("Cancelled.")
        return

    await conn.sendline(f"Starting {proto.upper()} send — begin your receiver now...")
    try:
        async with get_session() as session:
            await send_file_xyzmodem(
                session,
                file_entry.id,
                user,
                conn.reader,
                conn.writer,
                protocol=proto,
            )
        await conn.sendline("Transfer complete.")
    except (FileError, FileNotFound, FilePermissionDenied) as exc:
        await conn.sendline(f"Transfer failed: {exc}")
    except Exception:
        log.exception("Transfer error for file %s", file_entry.id)
        await conn.sendline("Transfer error.")


# ── Main menu ─────────────────────────────────────────────────────────────────


async def _main_menu(conn: _Conn, user: User, session_id: int) -> None:
    while True:
        await _touch_session(session_id)
        await conn.sendline()
        await conn.sendline(f"  {config.BBS_NAME}  [{user.username}]")
        await conn.hr()
        await conn.sendline("  [B] Message Boards")
        await conn.sendline("  [F] File Areas")
        await conn.sendline("  [G] Goodbye")
        await conn.sendline()
        await conn.send("Choice: ")

        try:
            key = (await conn.read_line(timeout=_MENU_TIMEOUT)).upper()
        except asyncio.TimeoutError:
            await conn.sendline("Timed out. Goodbye.")
            return

        if key == "B":
            await _boards_menu(conn, user, session_id)
        elif key == "F":
            await _files_menu(conn, user, session_id)
        elif key == "G" or key == "":
            await conn.sendline("Thanks for calling. Goodbye!")
            return


# ── Top-level connection handler ──────────────────────────────────────────────


async def handle_session(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    """Entry point for each accepted TCP connection."""
    peername = writer.get_extra_info("peername")
    addr = f"{peername[0]}:{peername[1]}" if peername else "unknown"
    log.info("Connection from %s", addr)

    session_id: int | None = None

    try:
        terminal = await _negotiate_terminal(reader, writer)
        log.info("%s identified as %s", addr, terminal.terminal_type.name)

        session_id = await _create_session_row(addr, terminal.terminal_type.value)
        conn = _Conn(reader, writer, terminal)

        await conn.banner()
        await conn.sendline("Type NEW to create an account.")

        user = await _login_screen(conn)
        if user is None:
            return

        await _update_session_user(session_id, user.id)
        await _main_menu(conn, user, session_id)

    except (ConnectionResetError, BrokenPipeError):
        log.info("%s disconnected", addr)
    except asyncio.TimeoutError:
        log.info("%s timed out", addr)
    except Exception:
        log.exception("Unhandled error in session %s", addr)
    finally:
        if session_id is not None:
            await _close_session_row(session_id)
        try:
            writer.close()
            await writer.wait_closed()
        except OSError:
            pass
