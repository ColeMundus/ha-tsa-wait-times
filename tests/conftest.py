"""Native HA discovery and loopback-only provider."""

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

    async def handler(request):
        requests.append(request.path)
        payload, status, headers = replies.popleft()
        return web.json_response(payload, status=status, headers=headers)

    app = web.Application()
    app.router.add_get("/feed", handler)
    server = await aiohttp_server(app, host="127.0.0.1", access_log=None)

    def add(payload=None, status=200, headers=None):
        replies.append((payload, status, headers))

    with patch(
        "custom_components.tsa_wait_times.client.URL", str(server.make_url("/feed"))
    ):
        yield SimpleNamespace(add=add, requests=requests)


@pytest.fixture
def payload():
    return {
        "WaitTimes": [
            {"CounterName": key, "DisplayText": str(i)}
            for i, key in enumerate(
                ("NorthGeneral", "NorthPrecheck", "SouthGeneral", "SouthPrecheck")
            )
        ],
        "NorthCheckpointClosed": False,
        "SouthCheckpointClosed": False,
    }
