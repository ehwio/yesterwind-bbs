"""PETSCII terminal — Commodore 64/128."""

from __future__ import annotations

from yesterwind_bbs.terminal.base import Terminal, TerminalType

# PETSCII control codes
_CLEAR_SCREEN = b"\x93"
_CURSOR_UP = b"\x91"
_CURSOR_DOWN = b"\x11"
_CURSOR_LEFT = b"\x9d"
_CURSOR_RIGHT = b"\x1d"
_RETURN = b"\x0d"
_DELETE = b"\x14"

# PETSCII colour codes (foreground)
_PETSCII_COLORS = {
    0: b"\x90",  # black
    1: b"\x05",  # white
    2: b"\x1c",  # red
    3: b"\x9f",  # cyan
    4: b"\x9c",  # purple
    5: b"\x1e",  # green
    6: b"\x1f",  # blue
    7: b"\x9e",  # yellow
}


class PetsciiTerminal(Terminal):
    terminal_type = TerminalType.PETSCII

    def encode(self, text: str) -> bytes:
        """
        Translate ASCII text to PETSCII.
        In PETSCII, uppercase letters are 0x41-0x5A but display as *graphics*
        in uppercase/graphics mode; lowercase 0x61-0x7A display as uppercase.
        We target lowercase PETSCII (shifted mode) so text reads naturally.
        """
        out = bytearray()
        for ch in text:
            c = ord(ch)
            if ch == "\n":
                out += _RETURN
            elif ch == "\r":
                pass
            elif 0x41 <= c <= 0x5A:
                # ASCII uppercase → PETSCII shifted lowercase (same code point)
                out.append(c)
            elif 0x61 <= c <= 0x7A:
                # ASCII lowercase → PETSCII uppercase display (subtract 0x20)
                out.append(c - 0x20)
            elif 0x20 <= c <= 0x40 or 0x5B <= c <= 0x60:
                out.append(c)
            else:
                out.append(0x3F)  # '?'
        return bytes(out)

    def clear_screen(self) -> bytes:
        return _CLEAR_SCREEN

    def move_cursor(self, row: int, col: int) -> bytes:
        return b""  # no PETSCII cursor-positioning sequence

    def set_color(self, fg: int | None = None, bg: int | None = None) -> bytes:
        if fg is not None and fg in _PETSCII_COLORS:
            return _PETSCII_COLORS[fg]
        return b""

    def reset_color(self) -> bytes:
        return _PETSCII_COLORS.get(1, b"")  # white

    def write(self, text: str) -> bytes:
        return self.encode(text) + _RETURN

    def decode_key(self, data: bytes) -> str:
        if data == _RETURN:
            return "ENTER"
        if data == _DELETE:
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
