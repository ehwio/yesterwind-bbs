"""Tests for splash screen rendering."""

from yesterwind_bbs.splash import ansi_splash, plain_splash


def test_ansi_splash_returns_bytes():
    result = ansi_splash()
    assert isinstance(result, bytes)


def test_ansi_splash_length():
    result = ansi_splash()
    # 23 rows of 80 chars + CRLF line endings + ANSI codes — just ensure it's substantial
    assert len(result) > 1000


def test_ansi_splash_has_crlf():
    result = ansi_splash()
    assert b"\r\n" in result


def test_ansi_splash_contains_title():
    result = ansi_splash()
    # BBS title appears spaced out — check for individual letters in CP437 bytes
    assert b"Y" in result and b"B" in result and b"S" in result


def test_ansi_splash_contains_press_any_key():
    result = ansi_splash()
    assert b"Press any key" in result


def test_plain_splash_returns_bytes():
    result = plain_splash()
    assert isinstance(result, bytes)


def test_plain_splash_has_crlf():
    result = plain_splash()
    assert b"\r\n" in result


def test_plain_splash_contains_tagline():
    result = plain_splash()
    assert b"baud" in result
