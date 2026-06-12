"""Base terminal abstraction."""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod


class TerminalType(enum.Enum):
    ANSI = "1"  # ANSI/VT100 — DOS, Windows, Mac, Linux, Amiga
    ATASCII = "2"  # Atari 8-bit
    PETSCII = "3"  # Commodore 64/128
    ASCII = "4"  # Plain 7-bit ASCII fallback

    @classmethod
    def from_choice(cls, char: str) -> TerminalType | None:
        for member in cls:
            if member.value == char:
                return member
        return None

    @classmethod
    def from_ttype(cls, ttype: str) -> TerminalType | None:
        """Map a Telnet TTYPE string to a TerminalType, or None if unrecognised."""
        t = ttype.upper()
        if any(k in t for k in ("ANSI", "VT100", "VT220", "XTERM", "SCREEN", "RXVT")):
            return cls.ANSI
        if "ATASCII" in t:
            return cls.ATASCII
        if "PETSCII" in t or "C64" in t:
            return cls.PETSCII
        return None


# Plain-ASCII greeting sent before terminal type is known.
# Must be safe 7-bit ASCII — no escape sequences, no IAC bytes.
TERMINAL_MENU: bytes = (
    b"\r\n"
    b"YESTERWIND BBS\r\n"
    b"\r\n"
    b"Terminal type:\r\n"
    b"  1. ANSI/VT100  (DOS, Windows, Mac, Linux, Amiga)\r\n"
    b"  2. ATASCII     (Atari 8-bit)\r\n"
    b"  3. PETSCII     (Commodore 64/128)\r\n"
    b"  4. Plain ASCII (anything else)\r\n"
    b"\r\n"
    b"Your choice: "
)


class Terminal(ABC):
    """
    Per-session terminal codec.

    Subclasses translate logical BBS output (text, colour, cursor control)
    into the byte sequences appropriate for the remote terminal type, and
    translate incoming bytes into canonical key events.
    """

    terminal_type: TerminalType

    # ── Output ────────────────────────────────────────────────────────────────

    @abstractmethod
    def encode(self, text: str) -> bytes:
        """Encode a Unicode string for this terminal's character set."""

    @abstractmethod
    def clear_screen(self) -> bytes:
        """Return bytes that clear the screen."""

    @abstractmethod
    def move_cursor(self, row: int, col: int) -> bytes:
        """Return bytes that move the cursor to (row, col) (1-based)."""

    @abstractmethod
    def set_color(self, fg: int | None = None, bg: int | None = None) -> bytes:
        """Return bytes that set foreground/background colour (ANSI colour indices)."""

    @abstractmethod
    def reset_color(self) -> bytes:
        """Return bytes that reset colour to terminal default."""

    # ── Input ─────────────────────────────────────────────────────────────────

    @abstractmethod
    def decode_key(self, data: bytes) -> str:
        """
        Translate raw bytes from the network into a canonical key name.
        Single printable characters are returned as-is; special keys use
        names like "UP", "DOWN", "ENTER", "BACKSPACE", "F1" … "F10".
        """

    # ── Convenience ───────────────────────────────────────────────────────────

    def write(self, text: str) -> bytes:
        """Encode text and append a CR+LF line ending."""
        return self.encode(text) + b"\r\n"
