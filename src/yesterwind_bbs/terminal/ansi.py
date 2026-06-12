"""ANSI/VT100 terminal — DOS, Windows, Mac, Linux, Amiga."""

from __future__ import annotations

from yesterwind_bbs.terminal.base import Terminal, TerminalType


class AnsiTerminal(Terminal):
    terminal_type = TerminalType.ANSI

    # CP437 is the native encoding for DOS ANSI art; we use it so that
    # .ans files load correctly and box-drawing chars render on old hardware.
    # Modern xterm/iTerm render the Unicode equivalents fine.
    _ENCODING = "cp437"

    def encode(self, text: str) -> bytes:
        return text.encode(self._ENCODING, errors="replace")

    def clear_screen(self) -> bytes:
        return b"\x1b[2J\x1b[H"

    def move_cursor(self, row: int, col: int) -> bytes:
        return f"\x1b[{row};{col}H".encode("ascii")

    def set_color(self, fg: int | None = None, bg: int | None = None) -> bytes:
        parts: list[str] = []
        if fg is not None:
            parts.append(str(30 + fg) if fg < 8 else str(90 + fg - 8))
        if bg is not None:
            parts.append(str(40 + bg) if bg < 8 else str(100 + bg - 8))
        if not parts:
            return b""
        return f"\x1b[{';'.join(parts)}m".encode("ascii")

    def reset_color(self) -> bytes:
        return b"\x1b[0m"

    def decode_key(self, data: bytes) -> str:
        if data == b"\r" or data == b"\n":
            return "ENTER"
        if data in (b"\x7f", b"\x08"):
            return "BACKSPACE"
        if data == b"\x1b[A":
            return "UP"
        if data == b"\x1b[B":
            return "DOWN"
        if data == b"\x1b[C":
            return "RIGHT"
        if data == b"\x1b[D":
            return "LEFT"
        try:
            return data.decode(self._ENCODING)
        except (UnicodeDecodeError, ValueError):
            return ""
