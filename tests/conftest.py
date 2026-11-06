"""Native HA discovery and loopback-only synthetic website fixtures."""

import asyncio
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import pytest_socket
from aiohttp import web

import custom_components

custom_components.__path__.append(
    str(Path(__file__).resolve().parents[1] / "custom_components")
)

AIRPORTS = {
    "AUS": "Austin-Bergstrom-International",
    "ATL": "Hartsfield-Jackson-Atlanta-International",
    "PDX": "Portland-International",
    "DJT": "President-Donald-J.-Trump-International",
}
CATALOG = (
    '<div class="list-group">'
    + "".join(
        f'<a href="/security-wait-times/{code}/{slug}">{code} : Synthetic {code}</a>'
        for code, slug in AIRPORTS.items()
    )
    + "</div>"
)


def page(code="PDX", duration="19 minutes and 42 seconds*", precheck="Available"):
    """Invented values in the verified website structure; no live fixtures."""
    return f"""<html><div id="predict_now"><p class="bold">{duration}</p></div>
<div id="hourly_predictions"><p class="lead">{code} : Example, ZZ</p>
<div class="row"><div class="col-md-4">1 am - 2 am</div><div>
<div class="progress-bar" aria-valuenow="90">7 m</div></div></div>
<div class="row"><div class="col-md-4">3 am - 4 am</div><div>
<div class="progress-bar">0 m</div></div></div></div>
<div id="precheck_status"><h4><span>{precheck}</span></h4><p>Terminal TEST</p><ul>
<li>Checkpoint A <span class="badge">Open</span></li>
<li>Checkpoint B <span class="badge">Closed</span></li></ul></div></html>"""


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    yield


@pytest.hookimpl(trylast=True)
def pytest_runtest_setup():
    pytest_socket.socket_allow_hosts(["127.0.0.1"], allow_unix_socket=True)


@pytest.fixture
async def http(aiohttp_server, socket_enabled):
    pytest_socket.socket_allow_hosts(["127.0.0.1"], allow_unix_socket=True)
    replies = deque()
    requests = []
    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(request):
        requests.append(request.path)
        payload, status, headers, blocked = replies.popleft()
        if blocked:
            started.set()
            await release.wait()
        return web.Response(
            text=payload, content_type="text/html", status=status, headers=headers
        )

    app = web.Application()
    app.router.add_get("/{tail:.*}", handler)
    server = await aiohttp_server(app, host="127.0.0.1", access_log=None)

    def add(payload="", status=200, headers=None, blocked=False):
        replies.append((payload, status, headers, blocked))

    with patch(
        "custom_components.tsa_wait_times.client.BASE_URL",
        str(server.make_url("")).rstrip("/"),
    ):
        yield SimpleNamespace(
            add=add, requests=requests, started=started, release=release
        )


@pytest.fixture
def payload():
    return page()


@pytest.fixture
def airport():
    from custom_components.tsa_wait_times.client import parse_catalog

    return parse_catalog(CATALOG)["PDX"]


@pytest.fixture
async def seeded(hass):
    """Skip catalog HTTP only where testing the per-airport runtime seam."""
    from custom_components.tsa_wait_times import get_feed
    from custom_components.tsa_wait_times.client import parse_catalog

    feed = get_feed(hass)
    feed.catalog = parse_catalog(CATALOG)
    feed.catalog_until = float("inf")
    return feed


def entry_data(code="PDX", minutes=5):
    return {
        "airport": code,
        "path": f"/security-wait-times/{code}/{AIRPORTS[code]}",
        "name": f"Synthetic {code}",
        "scan_interval": minutes,
    }
