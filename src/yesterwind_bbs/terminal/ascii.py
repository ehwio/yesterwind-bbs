"""Plain 7-bit ASCII terminal — safe fallback for anything."""

from __future__ import annotations

from yesterwind_bbs.terminal.base import Terminal, TerminalType


class AsciiTerminal(Terminal):
    terminal_type = TerminalType.ASCII

    def encode(self, text: str) -> bytes:
        return text.encode("ascii", errors="replace")

    def clear_screen(self) -> bytes:
        return b"\r\n" * 24

    def move_cursor(self, row: int, col: int) -> bytes:
        return b""

    def set_color(self, fg: int | None = None, bg: int | None = None) -> bytes:
        return b""

    def reset_color(self) -> bytes:
        return b""

    def decode_key(self, data: bytes) -> str:
        if data in (b"\r", b"\n"):
            return "ENTER"
        if data in (b"\x7f", b"\x08"):
            return "BACKSPACE"
        try:
            return data.decode("ascii")
        except (UnicodeDecodeError, ValueError):
            return ""
