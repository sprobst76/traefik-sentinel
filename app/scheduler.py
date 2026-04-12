"""Digest scheduler — daily asyncio background task.

Computes next wall-clock fire time at DIGEST_HOUR:00 UTC on each iteration
(next-fire calculation, D-21). Miss policy: if started after DIGEST_HOUR today,
waits until tomorrow (D-22).

CancelledError from asyncio.sleep propagates to the caller (lifespan). Do not
suppress it here — only the send_digest() call gets try/except Exception (D-23).

Timezone: hardcoded UTC via zoneinfo.ZoneInfo("UTC") per D-26 and SCHED-05.
Always use datetime.now(UTC) — never the deprecated naive UTC helper.
"""

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import DIGEST_HOUR
from app.digest import send_digest

UTC = ZoneInfo("UTC")


def _seconds_until_next_fire(hour: int) -> float:
    """Return seconds from now until the next occurrence of `hour`:00:00 UTC.

    Always returns a strictly positive value. If `hour`:00:00 already passed today,
    returns seconds until `hour`:00:00 tomorrow (miss policy D-22).
    """
    now = datetime.now(UTC)
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def digest_scheduler() -> None:
    """Run the daily digest on a next-fire loop.

    Designed for asyncio.create_task(). Runs until cancelled. CancelledError from
    asyncio.sleep propagates naturally; the lifespan shutdown block suppresses it
    once (D-23). A failed send_digest() is logged but does not stop the loop.
    """
    while True:
        seconds = _seconds_until_next_fire(DIGEST_HOUR)
        next_fire = datetime.now(UTC) + timedelta(seconds=seconds)
        print(f"Digest scheduler: next fire at {next_fire.isoformat()}")

        await asyncio.sleep(seconds)  # CancelledError propagates here — do not catch

        try:
            result = await send_digest()
            print(f"Digest scheduler: send_digest completed — {result}")
        except Exception as e:
            print(f"Digest scheduler: send_digest raised exception: {e}")
