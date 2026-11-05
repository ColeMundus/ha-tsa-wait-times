"""Anonymous first-party PDX website feed; no TSA national API."""

import asyncio
import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import COUNTERS

URL = "https://www.flypdx.com/TSAWaitTimesRefresh"


class FeedError(Exception):
    """Sanitized provider failure."""


@dataclass(frozen=True)
class Snapshot:
    """Only documented presentation fields, not raw provider content."""

    waits: dict[str, int | None]
    closed: dict[str, bool]


def parse(payload: Any) -> Snapshot:
    """Reject structural changes; unknown/missing values are never zero."""
    if not isinstance(payload, dict) or not isinstance(payload.get("WaitTimes"), list):
        raise FeedError("Unexpected feed structure")
    closed = {}
    for side in ("North", "South"):
        value = payload.get(f"{side}CheckpointClosed")
        if not isinstance(value, bool):
            raise FeedError("Missing checkpoint status")
        closed[side] = value
    waits: dict[str, int | None] = dict.fromkeys(COUNTERS)
    seen = set()
    for row in payload["WaitTimes"]:
        if not isinstance(row, dict):
            raise FeedError("Unexpected counter structure")
        key = row.get("CounterName")
        if not isinstance(key, str) or key not in COUNTERS:
            continue
        if key in seen:
            raise FeedError("Duplicate counter")
        seen.add(key)
        value = row.get("DisplayText")
        if (
            isinstance(value, str)
            and value.isascii()
            and value.isdecimal()
            and len(value) <= 6
        ):
            waits[key] = int(value)
        if closed["North" if key.startswith("North") else "South"]:
            waits[key] = None
    return Snapshot(waits, closed)


def retry_seconds(value: str | None) -> float:
    """Bound both delta and HTTP-date Retry-After, including hostile numbers."""
    try:
        seconds = float(value or "60")
    except ValueError:
        try:
            seconds = (
                parsedate_to_datetime(value or "") - datetime.now(UTC)
            ).total_seconds()
        except (ValueError, TypeError, OverflowError):
            seconds = 60
    if not math.isfinite(seconds):
        seconds = 3600
    return min(3600, max(60, seconds))


class Feed:
    """HA-lifetime shared pacing survives flow cancellation and entry reload."""

    def __init__(self, session: ClientSession) -> None:
        self.session = session
        self.lock = asyncio.Lock()
        self.not_before = 0.0
        self.snapshot: Snapshot | None = None
        self.failed = False

    async def fetch(self) -> Snapshot:
        """Reserve the deadline before HTTP and serialize concurrent consumers."""
        async with self.lock:
            now = time.monotonic()
            if now < self.not_before:
                if self.snapshot is not None and not self.failed:
                    return self.snapshot
                raise FeedError("Provider cooldown active")
            self.not_before = now + 60
            self.failed = True
            try:
                async with self.session.get(
                    URL, timeout=ClientTimeout(total=20)
                ) as response:
                    if response.status == 429:
                        self.not_before = time.monotonic() + retry_seconds(
                            response.headers.get("Retry-After")
                        )
                        raise FeedError("Provider rate limited")
                    if response.status != 200:
                        raise FeedError("Provider HTTP error")
                    payload = await response.json()
                snapshot = parse(payload)
            except (ClientError, TimeoutError, ValueError, RecursionError):
                raise FeedError("Unable to read airport feed") from None
            self.snapshot = snapshot
            self.failed = False
            return snapshot
