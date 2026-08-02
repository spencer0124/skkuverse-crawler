"""Read one source's notices. No database, no configuration, no env vars.

Run it: python examples/quickstart.py
"""

import asyncio
import logging

import structlog

from skkuverse_crawler import iter_notices

# The crawler logs through structlog, and so do the strategies it loads.
# Where that goes is the application's call, not the library's — silence
# it here so the output below is only notices.
structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL))


async def main() -> None:
    async for notice in iter_notices("skku-main"):
        print(f"{notice.date}  {notice.title}")


asyncio.run(main())
