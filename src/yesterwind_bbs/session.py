"""
Per-connection session — handles the terminal handshake and drives the
BBS menu state machine.
"""

from __future__ import annotations

import asyncio
import logging

from yesterwind_bbs import telnet
from yesterwind_bbs.terminal.ansi import AnsiTerminal
from yesterwind_bbs.terminal.ascii import AsciiTerminal
from yesterwind_bbs.terminal.atascii import AtasciiTerminal
from yesterwind_bbs.terminal.base import TERMINAL_MENU, Terminal, TerminalType
from yesterwind_bbs.terminal.petscii import PetsciiTerminal

log = logging.getLogger(__name__)

_TERMINAL_MAP: dict[TerminalType, type[Terminal]] = {
    TerminalType.ANSI: AnsiTerminal,
    TerminalType.ATASCII: AtasciiTerminal,
    TerminalType.PETSCII: PetsciiTerminal,
    TerminalType.ASCII: AsciiTerminal,
}

# Seconds to wait for user to answer the terminal-type menu
_MENU_TIMEOUT = 120.0


async def handle_session(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    """Entry point for each accepted TCP connection."""
    peername = writer.get_extra_info("peername")
    addr = f"{peername[0]}:{peername[1]}" if peername else "unknown"
    log.info("Connection from %s", addr)

    try:
        terminal = await _negotiate_terminal(reader, writer)
        log.info("%s identified as %s", addr, terminal.terminal_type.name)
        # TODO: hand off to login / main menu
        await writer.drain()
    except (ConnectionResetError, BrokenPipeError):
        log.info("%s disconnected", addr)
    except asyncio.TimeoutError:
        log.info("%s timed out during terminal negotiation", addr)
    except Exception:
        log.exception("Unhandled error in session %s", addr)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except OSError:
            pass


async def _negotiate_terminal(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> Terminal:
    """
    Determine the remote terminal type.

    Strategy:
      1. Listen passively for 250 ms — modern clients often announce TTYPE.
      2. If we get a recognisable TTYPE, use it silently.
      3. Otherwise send the plain-ASCII terminal-type menu and wait for a
         single keypress.  Old hardware sees zero garbage either way.
    """
    ttype_str = await telnet.passive_detect(reader)
    if ttype_str:
        detected = TerminalType.from_ttype(ttype_str)
        if detected:
            log.debug("Auto-detected terminal: %s (%s)", detected.name, ttype_str)
            return _TERMINAL_MAP[detected]()

    # Send the plain-ASCII menu — safe for every terminal at any baud rate
    writer.write(TERMINAL_MENU)
    await writer.drain()

    while True:
        try:
            data = await asyncio.wait_for(reader.read(1), timeout=_MENU_TIMEOUT)
        except asyncio.TimeoutError:
            writer.write(b"\r\nTimed out.\r\n")
            await writer.drain()
            raise

        if not data:
            raise ConnectionResetError("Client disconnected during terminal selection")

        choice = data.decode("ascii", errors="replace").strip()
        term_type = TerminalType.from_choice(choice)
        if term_type:
            return _TERMINAL_MAP[term_type]()

        writer.write(b"Invalid choice. Enter 1, 2, 3, or 4: ")
        await writer.drain()
