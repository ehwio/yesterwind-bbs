"""Tests for terminal codec layer."""

from yesterwind_bbs.terminal.ansi import AnsiTerminal
from yesterwind_bbs.terminal.ascii import AsciiTerminal
from yesterwind_bbs.terminal.atascii import AtasciiTerminal
from yesterwind_bbs.terminal.base import TERMINAL_MENU, TerminalType
from yesterwind_bbs.terminal.petscii import PetsciiTerminal

# ── TerminalType ──────────────────────────────────────────────────────────────


class TestTerminalType:
    def test_from_choice_valid(self):
        assert TerminalType.from_choice("1") == TerminalType.ANSI
        assert TerminalType.from_choice("2") == TerminalType.ATASCII
        assert TerminalType.from_choice("3") == TerminalType.PETSCII
        assert TerminalType.from_choice("4") == TerminalType.ASCII

    def test_from_choice_invalid(self):
        assert TerminalType.from_choice("5") is None
        assert TerminalType.from_choice("") is None
        assert TerminalType.from_choice("A") is None

    def test_from_ttype_ansi(self):
        for ttype in ("XTERM-256COLOR", "VT100", "ANSI", "SCREEN"):
            assert TerminalType.from_ttype(ttype) == TerminalType.ANSI

    def test_from_ttype_atascii(self):
        assert TerminalType.from_ttype("ATASCII") == TerminalType.ATASCII

    def test_from_ttype_petscii(self):
        assert TerminalType.from_ttype("PETSCII") == TerminalType.PETSCII
        assert TerminalType.from_ttype("C64") == TerminalType.PETSCII

    def test_from_ttype_unknown(self):
        assert TerminalType.from_ttype("UNKNOWN-TERMINAL") is None


# ── TERMINAL_MENU ─────────────────────────────────────────────────────────────


class TestTerminalMenu:
    def test_menu_is_pure_ascii(self):
        assert all(b < 0x80 for b in TERMINAL_MENU), "Menu contains non-ASCII bytes"

    def test_menu_has_no_escape_sequences(self):
        assert 0x1B not in TERMINAL_MENU, "Menu contains ESC byte"

    def test_menu_has_no_iac(self):
        assert 0xFF not in TERMINAL_MENU, "Menu contains IAC byte"

    def test_menu_contains_all_options(self):
        text = TERMINAL_MENU.decode("ascii")
        assert "1." in text
        assert "2." in text
        assert "3." in text
        assert "4." in text


# ── ANSI terminal ─────────────────────────────────────────────────────────────


class TestAnsiTerminal:
    def setup_method(self):
        self.t = AnsiTerminal()

    def test_encode_ascii(self):
        assert self.t.encode("Hello") == b"Hello"

    def test_encode_replaces_unmappable(self):
        result = self.t.encode("中")  # CJK char not in CP437
        assert len(result) == 1  # replaced with single byte

    def test_clear_screen(self):
        assert self.t.clear_screen() == b"\x1b[2J\x1b[H"

    def test_move_cursor(self):
        assert self.t.move_cursor(5, 10) == b"\x1b[5;10H"

    def test_set_color(self):
        result = self.t.set_color(fg=1)  # red
        assert b"\x1b[" in result
        assert b"m" in result

    def test_reset_color(self):
        assert self.t.reset_color() == b"\x1b[0m"

    def test_decode_key_enter(self):
        assert self.t.decode_key(b"\r") == "ENTER"
        assert self.t.decode_key(b"\n") == "ENTER"

    def test_decode_key_backspace(self):
        assert self.t.decode_key(b"\x7f") == "BACKSPACE"
        assert self.t.decode_key(b"\x08") == "BACKSPACE"

    def test_decode_key_arrows(self):
        assert self.t.decode_key(b"\x1b[A") == "UP"
        assert self.t.decode_key(b"\x1b[B") == "DOWN"
        assert self.t.decode_key(b"\x1b[C") == "RIGHT"
        assert self.t.decode_key(b"\x1b[D") == "LEFT"

    def test_decode_key_printable(self):
        assert self.t.decode_key(b"A") == "A"
        assert self.t.decode_key(b"1") == "1"


# ── ATASCII terminal ──────────────────────────────────────────────────────────


class TestAtasciiTerminal:
    def setup_method(self):
        self.t = AtasciiTerminal()

    def test_encode_printable(self):
        assert self.t.encode("Hello") == b"Hello"

    def test_encode_newline_becomes_eol(self):
        result = self.t.encode("Hi\n")
        assert result.endswith(b"\x9b")

    def test_encode_cr_is_dropped(self):
        assert self.t.encode("\r\n") == b"\x9b"

    def test_encode_non_ascii_replaced(self):
        result = self.t.encode("\xff")
        assert result == b"?"

    def test_clear_screen(self):
        assert self.t.clear_screen() == b"\x7d"

    def test_no_color_or_cursor(self):
        assert self.t.set_color(fg=1) == b""
        assert self.t.reset_color() == b""
        assert self.t.move_cursor(1, 1) == b""

    def test_write_uses_atascii_eol(self):
        result = self.t.write("Hi")
        assert result.endswith(b"\x9b")

    def test_decode_key_enter(self):
        assert self.t.decode_key(b"\x9b") == "ENTER"

    def test_decode_key_backspace(self):
        assert self.t.decode_key(b"\x7e") == "BACKSPACE"

    def test_decode_key_arrows(self):
        assert self.t.decode_key(b"\x1c") == "UP"
        assert self.t.decode_key(b"\x1d") == "DOWN"


# ── PETSCII terminal ──────────────────────────────────────────────────────────


class TestPetsciiTerminal:
    def setup_method(self):
        self.t = PetsciiTerminal()

    def test_encode_uppercase_passthrough(self):
        result = self.t.encode("HELLO")
        assert result == b"HELLO"

    def test_encode_lowercase_shifted(self):
        result = self.t.encode("hello")
        # lowercase → subtract 0x20 in PETSCII shifted mode
        assert result == bytes([ord("H"), ord("E"), ord("L"), ord("L"), ord("O")])

    def test_encode_newline(self):
        assert self.t.encode("\n") == b"\x0d"

    def test_clear_screen(self):
        assert self.t.clear_screen() == b"\x93"

    def test_no_cursor_positioning(self):
        assert self.t.move_cursor(1, 1) == b""

    def test_decode_key_enter(self):
        assert self.t.decode_key(b"\x0d") == "ENTER"

    def test_decode_key_delete(self):
        assert self.t.decode_key(b"\x14") == "BACKSPACE"


# ── ASCII terminal ────────────────────────────────────────────────────────────


class TestAsciiTerminal:
    def setup_method(self):
        self.t = AsciiTerminal()

    def test_encode(self):
        assert self.t.encode("Hello") == b"Hello"

    def test_encode_replaces_non_ascii(self):
        result = self.t.encode("\xff")
        assert result == b"?"

    def test_clear_screen_is_blank_lines(self):
        result = self.t.clear_screen()
        assert b"\r\n" in result
        assert b"\x1b" not in result

    def test_no_color_or_cursor(self):
        assert self.t.set_color(fg=1) == b""
        assert self.t.reset_color() == b""
        assert self.t.move_cursor(1, 1) == b""

    def test_decode_key_enter(self):
        assert self.t.decode_key(b"\r") == "ENTER"
        assert self.t.decode_key(b"\n") == "ENTER"

    def test_decode_key_backspace(self):
        assert self.t.decode_key(b"\x7f") == "BACKSPACE"
