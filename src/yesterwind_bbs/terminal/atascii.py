"""ATASCII terminal — Atari 8-bit (400/800/XL/XE)."""

from __future__ import annotations

from yesterwind_bbs.terminal.base import Terminal, TerminalType

# ATASCII control codes (subset used for BBS navigation)
_CLEAR_SCREEN = b"\x7d"  # Atari clear screen
_CURSOR_UP = b"\x1c"
_CURSOR_DOWN = b"\x1d"
_CURSOR_LEFT = b"\x1e"
_CURSOR_RIGHT = b"\x1f"
_BACKSPACE = b"\x7e"  # Atari backspace / delete
_EOL = b"\x9b"  # ATASCII end-of-line (not CR+LF)

# ATASCII has no colour or cursor-positioning sequences; stubs return empty bytes.


class AtasciiTerminal(Terminal):
    terminal_type = TerminalType.ATASCII

    def encode(self, text: str) -> bytes:
        """
        Translate ASCII/Latin-1 text to ATASCII bytes.
        Lowercase a-z maps to ATASCII 97-122 (same as ASCII).
        Uppercase A-Z maps to ATASCII 65-90 (same as ASCII).
        Line endings become ATASCII EOL (0x9B).
        Non-representable characters are replaced with '?'.
        """
        out = bytearray()
        for ch in text:
            if ch == "\n":
                out += _EOL
            elif ch == "\r":
                pass  # swallow bare CR; newlines are handled by \n
            elif 0x20 <= ord(ch) <= 0x7E:
                out.append(ord(ch))
            else:
                out.append(ord("?"))
        return bytes(out)

    def clear_screen(self) -> bytes:
        return _CLEAR_SCREEN

    def move_cursor(self, row: int, col: int) -> bytes:
        return b""  # ATASCII has no cursor-positioning sequence

    def set_color(self, fg: int | None = None, bg: int | None = None) -> bytes:
        return b""  # no colour support

    def reset_color(self) -> bytes:
        return b""

    def write(self, text: str) -> bytes:
        """Encode text with ATASCII EOL instead of CR+LF."""
        return self.encode(text) + _EOL

    def decode_key(self, data: bytes) -> str:
        if data == _EOL or data == b"\r":
            return "ENTER"
        if data == _BACKSPACE:
            return "BACKSPACE"
        if data == _CURSOR_UP:
            return "UP"
        if data == _CURSOR_DOWN:
            return "DOWN"
        if data == _CURSOR_LEFT:
            return "LEFT"
        if data == _CURSOR_RIGHT:
            return "RIGHT"
        if len(data) == 1 and 0x20 <= data[0] <= 0x7E:
            return chr(data[0])
        return ""
