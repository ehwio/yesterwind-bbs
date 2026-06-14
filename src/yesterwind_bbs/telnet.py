"""
Telnet option negotiation helpers.

We follow a passive-first strategy:
  1. Wait briefly for the client to send unsolicited IAC bytes.
  2. If IAC bytes arrive, respond and attempt TTYPE negotiation.
  3. If nothing arrives within the timeout, skip negotiation entirely.

This ensures old hardware (Atari, C64, etc.) sees zero garbage before
the plain-ASCII terminal-type menu.
"""

from __future__ import annotations

import asyncio

# Telnet command bytes
IAC = 0xFF
DONT = 0xFE
DO = 0xFD
WONT = 0xFC
WILL = 0xFB
SB = 0xFA  # subnegotiation begin
SE = 0xF0  # subnegotiation end

# Telnet option codes
OPT_ECHO = 0x01
OPT_SGA = 0x03  # suppress go-ahead
OPT_TTYPE = 0x18  # terminal type
OPT_NAWS = 0x1F  # negotiate about window size

# TTYPE subnegotiation
TTYPE_IS = 0x00
TTYPE_SEND = 0x01

# How long to wait for unsolicited IAC before giving up
_PASSIVE_TIMEOUT = 0.25  # seconds


async def passive_detect(
    reader: asyncio.StreamReader,
) -> str | None:
    """
    Wait briefly for the client to volunteer its terminal type via TTYPE.
    Returns the TTYPE string (e.g. "XTERM-256COLOR") or None.
    Consumes only IAC negotiation bytes; leaves other data in the stream.
    """
    try:
        first = await asyncio.wait_for(reader.read(1), timeout=_PASSIVE_TIMEOUT)
    except asyncio.TimeoutError:
        return None

    if not first:
        # EOF before any data (e.g. healthcheck that connects and immediately closes)
        return None
    if first[0] != IAC:
        # Client sent non-IAC data (e.g. an immediate keypress) — put it back
        reader.feed_data(first)
        return None

    # Client started a negotiation — read and discard until we get nothing
    # more within a short window.  A full TTYPE exchange requires the server
    # to respond, which we deliberately avoid here; this path only catches
    # clients that proactively announce WILL TTYPE.
    buf = bytearray(first)
    try:
        rest = await asyncio.wait_for(reader.read(256), timeout=_PASSIVE_TIMEOUT)
        buf.extend(rest)
    except asyncio.TimeoutError:
        pass

    return _extract_ttype(bytes(buf))


def _extract_ttype(data: bytes) -> str | None:
    """
    Scan a raw byte buffer for a TTYPE IS subnegotiation and return the
    terminal-type string it contains, or None.
    """
    i = 0
    while i < len(data) - 1:
        if data[i] != IAC:
            i += 1
            continue
        cmd = data[i + 1]
        if cmd == SB and i + 2 < len(data) and data[i + 2] == OPT_TTYPE:
            # IAC SB TTYPE IS <name> IAC SE
            start = i + 4
            end = data.find(bytes([IAC, SE]), start)
            if end != -1:
                return data[start:end].decode("ascii", errors="replace").upper()
        i += 2
    return None


def build_will(option: int) -> bytes:
    return bytes([IAC, WILL, option])


def build_do(option: int) -> bytes:
    return bytes([IAC, DO, option])


def build_wont(option: int) -> bytes:
    return bytes([IAC, WONT, option])


def build_dont(option: int) -> bytes:
    return bytes([IAC, DONT, option])
