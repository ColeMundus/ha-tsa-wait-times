"""Anonymous TSAWaitTimes.com website client; no account or developer API."""

import asyncio
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

from aiohttp import ClientError, ClientSession, ClientTimeout

BASE_URL = "https://www.tsawaittimes.com"
CATALOG_PATH = "/airports"
PATH = re.compile(r"/security-wait-times/([A-Z0-9]{3})/([A-Za-z0-9.-]+)")
VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class FeedError(Exception):
    """Sanitized provider failure."""


@dataclass
class Node:
    """Minimal tree for the website's presentation markup."""

    tag: str
    attrs: dict[str, str]
    children: list[Node | str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(
            " ".join(
                c.text if isinstance(c, Node) else c for c in self.children
            ).split()
        )

    def find(self, tag: str = "", *, cls: str = "", id: str = "") -> list[Node]:
        result = []
        for child in self.children:
            if isinstance(child, Node):
                if (
                    (not tag or child.tag == tag)
                    and (not cls or cls in child.attrs.get("class", "").split())
                    and (not id or child.attrs.get("id") == id)
                ):
                    result.append(child)
                result.extend(child.find(tag, cls=cls, id=id))
        return result


class Tree(HTMLParser):
    """Parse HTML without third-party runtime dependencies."""

    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("root", {})
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, {k: v or "" for k, v in attrs})
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


@dataclass(frozen=True)
class Airport:
    """Exact directory identity and relative source URL."""

    code: str
    name: str
    path: str


def parse_catalog(html: str) -> dict[str, Airport]:
    """Use linked directory entries, not unsupported autocomplete results."""
    airports: dict[str, Airport] = {}
    for group in Tree(html).root.find(cls="list-group"):
        for link in group.find("a"):
            path = link.attrs.get("href", "")
            match = PATH.fullmatch(path)
            if not match:
                continue
            code = match[1]
            airport = Airport(code, link.text, path)
            if code in airports and airports[code] != airport:
                raise FeedError("Conflicting airport directory")
            airports[code] = airport
    if not airports:
        raise FeedError("Airport directory unavailable")
    return airports


@dataclass(frozen=True)
class Snapshot:
    """Modeled estimates, not measured checkpoint waits."""

    minutes: float | None
    precheck: bool | None
    checkpoints: tuple[dict[str, str], ...]
    hourly: tuple[dict[str, str | float], ...]
    fetched_at: datetime


def parse(html: str, airport: Airport) -> Snapshot:
    """Validate selected airport before accepting any presentation values."""
    root = Tree(html).root
    predictions = root.find(id="hourly_predictions")
    if not predictions or not any(
        re.match(rf"^{re.escape(airport.code)}\s*:", p.text)
        for p in predictions[0].find("p", cls="lead")
    ):
        raise FeedError("Airport identity missing or mismatched")
    minutes = None
    for container in root.find(id="predict_now"):
        for p in container.find("p", cls="bold"):
            match = re.fullmatch(
                r"(\d{1,4}) minutes? and (\d{1,2}) seconds?\*?", p.text
            )
            if match and int(match[2]) < 60:
                minutes = int(match[1]) + int(match[2]) / 60
    hourly: list[dict[str, str | float]] = []
    for row in predictions[0].find(cls="row"):
        bars = row.find(cls="progress-bar")
        columns = [c for c in row.children if isinstance(c, Node)]
        if bars and columns:
            match = re.fullmatch(
                r"(\d{1,4}(?:\.\d+)?)\s*(?:m|min(?:utes?)?)?", bars[0].text
            )
            if match:
                hourly.append(
                    {"time_slot": columns[0].text, "minutes": float(match[1])}
                )
    precheck = None
    checkpoints = []
    for container in root.find(id="precheck_status"):
        for heading in container.find("h4"):
            text = heading.text.lower()
            if "not available" in text or "unavailable" in text:
                precheck = False
            elif "available" in text:
                precheck = True
        terminal = ""
        for child in container.children:
            if not isinstance(child, Node):
                continue
            if child.tag == "p":
                terminal = child.text
            elif child.tag == "ul":
                for li in child.find("li"):
                    badges = li.find(cls="badge")
                    if badges and badges[0].text in {"Open", "Closed"}:
                        status = badges[0].text
                        checkpoints.append(
                            {
                                "terminal": terminal,
                                "checkpoint": li.text.removesuffix(status).strip(),
                                "status": status,
                            }
                        )
    return Snapshot(
        minutes, precheck, tuple(checkpoints), tuple(hourly), datetime.now(UTC)
    )


def retry_seconds(value: str | None) -> float:
    """Bound delta/date Retry-After, including overflow and nonfinite values."""
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
    """HA-lifetime shared catalog/cache and aggregate five-second pacing."""

    def __init__(self, session: ClientSession) -> None:
        self.session = session
        self.lock = asyncio.Lock()
        self.catalog: dict[str, Airport] = {}
        self.catalog_until = 0.0
        self.network_after = 0.0
        self.cooldown = 0.0
        self.deadlines: dict[str, float] = {}
        self.last_attempt: dict[str, float] = {}
        self.snapshots: dict[str, Snapshot] = {}
        self.failed: set[str] = set()

    def deadline(self, code: str) -> float:
        return max(self.deadlines.get(code, 0), self.cooldown)

    async def _read(self, path: str, active: Callable[[], bool] | None = None) -> str:
        if time.monotonic() < self.cooldown:
            raise FeedError("Provider cooldown active")
        delay = self.network_after - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        if active is not None and not active():
            raise FeedError("Entry retired")
        self.network_after = time.monotonic() + 5
        try:
            async with self.session.get(
                BASE_URL + path, timeout=ClientTimeout(total=20), allow_redirects=False
            ) as response:
                if response.status == 429:
                    self.cooldown = time.monotonic() + retry_seconds(
                        response.headers.get("Retry-After")
                    )
                    raise FeedError("Provider rate limited")
                if response.status != 200:
                    raise FeedError("Provider HTTP error")
                if response.content_length and response.content_length > 2_000_000:
                    raise FeedError("Provider response too large")
                # read(n) may return a partial chunk; collect until EOF or limit.
                body = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    body.extend(chunk)
                    if len(body) > 2_000_000:
                        raise FeedError("Provider response too large")
                return body.decode("utf-8")
        except (ClientError, TimeoutError, ValueError):
            raise FeedError("Unable to read airport website") from None

    async def airports(self) -> dict[str, Airport]:
        async with self.lock:
            if self.catalog and time.monotonic() < self.catalog_until:
                return self.catalog
            if time.monotonic() < self.catalog_until:
                raise FeedError("Directory cooldown active")
            self.catalog_until = time.monotonic() + 60
            try:
                self.catalog = parse_catalog(await self._read(CATALOG_PATH))
            except RecursionError:
                raise FeedError("Unexpected airport directory structure") from None
            self.catalog_until = time.monotonic() + 86400
            return self.catalog

    async def fetch(
        self,
        airport: Airport,
        interval: int = 5,
        *,
        active: Callable[[], bool] | None = None,
    ) -> Snapshot:
        """Coalesce reads and retain per-airport deadlines across reloads."""
        interval = max(5, interval)
        async with self.lock:
            if active is not None and not active():
                raise FeedError("Entry retired")
            now = time.monotonic()
            self.deadlines[airport.code] = max(
                self.deadlines.get(airport.code, 0),
                self.last_attempt[airport.code] + interval * 60
                if airport.code in self.last_attempt
                else 0,
            )
            if now < self.deadline(airport.code):
                if (
                    airport.code in self.snapshots
                    and airport.code not in self.failed
                    and now >= self.cooldown
                ):
                    return self.snapshots[airport.code]
                raise FeedError("Provider cooldown active")
            attempt = max(now, self.network_after)
            self.last_attempt[airport.code] = attempt
            self.deadlines[airport.code] = attempt + interval * 60
            self.failed.add(airport.code)
            try:
                snapshot = parse(await self._read(airport.path, active), airport)
            except RecursionError:
                raise FeedError("Unexpected airport page structure") from None
            finally:
                # asyncio sleep may wake late. Retain the *actual* request start
                # even on failure/cancellation, not just the pre-wait reservation.
                self.last_attempt[airport.code] = max(attempt, self.network_after - 5)
                self.deadlines[airport.code] = max(
                    self.deadlines[airport.code],
                    self.last_attempt[airport.code] + interval * 60,
                )
            if active is not None and not active():
                self.snapshots.pop(airport.code, None)
                raise FeedError("Entry retired")
            self.snapshots[airport.code] = snapshot
            self.failed.discard(airport.code)
            return snapshot
