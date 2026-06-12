"""Tests for Telnet negotiation helpers."""

from yesterwind_bbs.telnet import IAC, OPT_TTYPE, SB, SE, TTYPE_IS, _extract_ttype


class TestExtractTtype:
    def _make_ttype_packet(self, name: str) -> bytes:
        payload = name.encode("ascii")
        return bytes([IAC, SB, OPT_TTYPE, TTYPE_IS]) + payload + bytes([IAC, SE])

    def test_extracts_known_ttype(self):
        data = self._make_ttype_packet("XTERM-256COLOR")
        assert _extract_ttype(data) == "XTERM-256COLOR"

    def test_returns_uppercase(self):
        data = self._make_ttype_packet("xterm")
        assert _extract_ttype(data) == "XTERM"

    def test_returns_none_if_no_ttype(self):
        assert _extract_ttype(b"\xff\xfd\x18") is None

    def test_returns_none_on_empty(self):
        assert _extract_ttype(b"") is None

    def test_ignores_leading_garbage(self):
        data = b"\x00\x00" + self._make_ttype_packet("VT100")
        assert _extract_ttype(data) == "VT100"
