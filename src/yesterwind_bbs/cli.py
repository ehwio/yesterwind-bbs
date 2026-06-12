"""Command-line entry point for the BBS server."""

from __future__ import annotations

import asyncio
import logging


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    from yesterwind_bbs.server import serve

    asyncio.run(serve())


if __name__ == "__main__":
    main()
