"""Asyncio TCP server — accepts connections and spawns sessions."""

from __future__ import annotations

import asyncio
import logging
import signal

from yesterwind_bbs import config
from yesterwind_bbs.db.engine import init_db
from yesterwind_bbs.session import handle_session

log = logging.getLogger(__name__)


async def serve() -> None:
    await init_db()
    server = await asyncio.start_server(
        handle_session,
        host="0.0.0.0",
        port=config.BBS_PORT,
        limit=65536,
    )
    addrs = [s.getsockname() for s in server.sockets or []]
    log.info("Yesterwind BBS listening on %s", addrs)

    loop = asyncio.get_running_loop()
    stop = loop.create_future()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set_result, None)

    async with server:
        await server.start_serving()
        await stop
        log.info("Shutting down…")
