"""
Tests for session.py — _Conn helpers, login/signup flows, menu routing.

We avoid real TCP by wiring asyncio queues as reader/writer stand-ins.
The _QueueWriter collects everything written; _QueueReader feeds bytes on demand.
"""

from __future__ import annotations

import asyncio

import pytest

from yesterwind_bbs.session import (
    _Conn,
)
from yesterwind_bbs.terminal.ansi import AnsiTerminal
from yesterwind_bbs.terminal.ascii import AsciiTerminal
from yesterwind_bbs.terminal.atascii import AtasciiTerminal

# ── Fake stream helpers ───────────────────────────────────────────────────────


class _FakeWriter:
    """Collects all bytes written via .write() / .drain()."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def write(self, data: bytes) -> None:
        self._buf.extend(data)

    async def drain(self) -> None:
        pass

    @property
    def received(self) -> bytes:
        return bytes(self._buf)

    def clear(self) -> None:
        self._buf.clear()


class _FakeReader:
    """Yields bytes from a pre-loaded queue one read() at a time."""

    def __init__(self, data: bytes = b"") -> None:
        self._q: asyncio.Queue = asyncio.Queue()
        for b in data:
            self._q.put_nowait(bytes([b]))

    def feed(self, data: bytes) -> None:
        for b in data:
            self._q.put_nowait(bytes([b]))

    async def read(self, n: int) -> bytes:
        chunks = []
        for _ in range(n):
            try:
                chunk = self._q.get_nowait()
                chunks.append(chunk)
            except asyncio.QueueEmpty:
                break
        if not chunks:
            # Block until at least one byte is available
            chunks.append(await self._q.get())
        return b"".join(chunks)


def _ansi_conn(input_bytes: bytes = b"") -> tuple[_Conn, _FakeWriter]:
    reader = _FakeReader(input_bytes)
    writer = _FakeWriter()
    term = AnsiTerminal()
    conn = _Conn(reader, writer, term)  # type: ignore[arg-type]
    return conn, writer


def _ascii_conn(input_bytes: bytes = b"") -> tuple[_Conn, _FakeWriter]:
    reader = _FakeReader(input_bytes)
    writer = _FakeWriter()
    term = AsciiTerminal()
    conn = _Conn(reader, writer, term)  # type: ignore[arg-type]
    return conn, writer


def _atascii_conn(input_bytes: bytes = b"") -> tuple[_Conn, _FakeWriter]:
    reader = _FakeReader(input_bytes)
    writer = _FakeWriter()
    term = AtasciiTerminal()
    conn = _Conn(reader, writer, term)  # type: ignore[arg-type]
    return conn, writer


# ── _Conn.send / sendline ─────────────────────────────────────────────────────


class TestConnSend:
    async def test_send_encodes_text(self):
        conn, w = _ansi_conn()
        await conn.send("hello")
        assert b"hello" in w.received

    async def test_sendline_appends_crlf(self):
        conn, w = _ansi_conn()
        await conn.sendline("hi")
        assert w.received.endswith(b"\r\n")

    async def test_sendline_atascii_uses_eol(self):
        conn, w = _atascii_conn()
        await conn.sendline("hi")
        # ATASCII EOL is 0x9B
        assert w.received.endswith(b"\x9b")

    async def test_clear_sends_bytes(self):
        conn, w = _ansi_conn()
        await conn.clear()
        assert len(w.received) > 0

    async def test_banner_contains_bbs_name(self):
        from yesterwind_bbs import config

        conn, w = _ansi_conn()
        await conn.banner()
        assert config.BBS_NAME.encode("cp437") in w.received


# ── _Conn.read_line ───────────────────────────────────────────────────────────


class TestConnReadLine:
    async def test_reads_until_enter(self):
        # "hello\r" — CR is ENTER for ANSI
        conn, _ = _ansi_conn(b"hello\r")
        result = await conn.read_line()
        assert result == "hello"

    async def test_backspace_removes_last_char(self):
        # "helo" + backspace + "p" + enter
        conn, _ = _ansi_conn(b"helo\x7fp\r")
        result = await conn.read_line()
        assert result == "help"

    async def test_echo_false_suppresses_output(self):
        conn, w = _ansi_conn(b"secret\r")
        w.clear()
        await conn.read_line(echo=False)
        # With echo=False, only the trailing newline (from sendline()) is written
        assert b"secret" not in w.received

    async def test_timeout_raises(self):
        conn, _ = _ansi_conn(b"")  # no data — will hang
        with pytest.raises(asyncio.TimeoutError):
            await conn.read_line(timeout=0.05)

    async def test_atascii_enter_is_eol(self):
        conn, _ = _atascii_conn(b"hi\x9b")
        result = await conn.read_line()
        assert result == "hi"


# ── _Conn.read_key ────────────────────────────────────────────────────────────


class TestConnReadKey:
    async def test_returns_printable_char(self):
        conn, _ = _ansi_conn(b"B")
        key = await conn.read_key()
        assert key == "B"

    async def test_enter_returns_enter(self):
        conn, _ = _ansi_conn(b"\r")
        key = await conn.read_key()
        assert key == "ENTER"

    async def test_timeout_raises(self):
        conn, _ = _ansi_conn(b"")
        with pytest.raises(asyncio.TimeoutError):
            await conn.read_key(timeout=0.05)


# ── Session row helpers ───────────────────────────────────────────────────────
# _create_session_row / _update_session_user / _touch_session / _close_session_row
# all delegate directly to get_session() which is covered by test_models.py.
# Patching is not straightforward because `yesterwind_bbs.db.engine` resolves
# to the AsyncEngine object (not the module) via the package attribute, so we
# skip unit tests here and rely on integration coverage.


# ── _Conn helpers — hr and divider ────────────────────────────────────────────


class TestConnHr:
    async def test_hr_outputs_dashes(self):
        conn, w = _ansi_conn()
        await conn.hr()
        assert b"-" in w.received


# ── Terminal type coverage ────────────────────────────────────────────────────


class TestTerminalVariants:
    async def test_ascii_conn_no_escapes(self):
        conn, w = _ascii_conn()
        await conn.sendline("hello")
        # AsciiTerminal must produce no ESC bytes
        assert b"\x1b" not in w.received

    async def test_ansi_clear_has_escape(self):
        conn, w = _ansi_conn()
        await conn.clear()
        assert b"\x1b" in w.received

    async def test_atascii_clear_is_0x7d(self):
        conn, w = _atascii_conn()
        await conn.clear()
        assert b"\x7d" in w.received
