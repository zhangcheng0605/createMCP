"""Group 6 -- the HTTP transport and its auth gate (notes_mcp.http_app).

The stdio transport needs no authentication: the only process that can talk to
the server is the one that spawned it. Over HTTP that is no longer true, and the
bearer-token check in :mod:`notes_mcp.http_app` becomes the only thing between a
notes folder and the open internet. So these tests are less about MCP and more
about that gate: it must be on by default, it must reject every near-miss, and
opting out of it must be loud and deliberate.

Each test starts a real server subprocess on a free port and speaks real HTTP to
it, because the interesting failures here (a middleware that does not apply to
the mounted sub-app, a health check hidden behind auth) only show up over the
wire.
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import subprocess
import sys
import time

import httpx
import pytest

from conftest import REPO_ROOT

TOKEN = "test-token-cVQ7pW2r"
DEMO_NOTES = REPO_ROOT / "demo-notes"
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
PYTHON = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable


def free_port() -> int:
    """Ask the OS for a port nobody is using, to keep parallel runs apart."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def spawn(env_extra: dict[str, str], port: int) -> subprocess.Popen[str]:
    env = {
        **os.environ,
        "MCP_TRANSPORT": "http",
        "NOTES_DIR": str(DEMO_NOTES),
        "HOST": "127.0.0.1",
        "PORT": str(port),
        **env_extra,
    }
    # Clear every auth mechanism first, so a variable set in the developer's own
    # shell cannot quietly make a "no auth configured" test pass.
    for name in ("NOTES_TOKEN", "NOTES_URL_SECRET", "ALLOW_NO_AUTH"):
        env.pop(name, None)
    env.update(env_extra)
    return subprocess.Popen(
        [PYTHON, "-m", "notes_mcp.server"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def await_health(proc: subprocess.Popen[str], port: int, timeout: float = 20.0) -> bool:
    """True once /healthz answers; False if the process died first."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        try:
            if httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=1).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    return False


def terminate(proc: subprocess.Popen[str]) -> str:
    """Stop a *running* server and return whatever it wrote to stderr."""
    if proc.poll() is None:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()
            proc.wait(timeout=5)
    _, err = proc.communicate(timeout=10)
    return err or ""


def wait_for_exit(proc: subprocess.Popen[str], timeout: float = 30.0) -> str:
    """Let a server exit on its own and return its stderr.

    Deliberately *not* `terminate()`: signalling a process that is about to fail
    by itself can beat it to the punch, and then its diagnostic never reaches the
    pipe. Use this whenever the point of the test is the exit message.
    """
    _, err = proc.communicate(timeout=timeout)
    return err or ""


@pytest.fixture(scope="module")
def authed_server():
    """One token-protected HTTP server for the whole module."""
    port = free_port()
    proc = spawn({"NOTES_TOKEN": TOKEN}, port)
    if not await_health(proc, port):
        pytest.fail(f"server did not come up: {terminate(proc)}")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        terminate(proc)


# --------------------------------------------------------------------------- #
# The gate is on by default
# --------------------------------------------------------------------------- #


def test_refuses_to_start_over_http_without_a_token():
    """Forgetting the token must not silently publish the notes folder."""
    port = free_port()
    proc = spawn({}, port)
    err = wait_for_exit(proc)

    assert proc.returncode != 0
    assert "NOTES_TOKEN" in err  # tells the operator how to fix it
    assert "anyone with the URL" in err  # and what the alternative costs


def test_stdio_still_needs_no_token():
    """The default transport is unaffected by any of this.

    Guards the obvious regression: routing every startup through the HTTP auth
    check would break the local stdio setup, which needs no token because no
    network is involved.
    """
    env = {**os.environ, "NOTES_DIR": str(DEMO_NOTES)}
    env.pop("NOTES_TOKEN", None)
    env.pop("MCP_TRANSPORT", None)
    proc = subprocess.Popen(
        [PYTHON, "-m", "notes_mcp.server"],
        cwd=REPO_ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(2.0)
    alive = proc.poll() is None
    proc.kill()
    out, err = proc.communicate(timeout=10)

    assert alive, f"stdio server exited unexpectedly: {err}"
    assert "serving 11 note(s)" in err
    assert "over stdio" in err
    assert out == "", "stdio transport must keep stdout free for JSON-RPC"


def test_invalid_transport_name_is_rejected():
    env = {**os.environ, "NOTES_DIR": str(DEMO_NOTES), "MCP_TRANSPORT": "carrier-pigeon"}
    proc = subprocess.Popen(
        [PYTHON, "-m", "notes_mcp.server"],
        cwd=REPO_ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    out, err = proc.communicate(timeout=30)
    assert proc.returncode == 1
    assert "carrier-pigeon" in err
    assert out == ""


# --------------------------------------------------------------------------- #
# What the gate lets through, and what it does not
# --------------------------------------------------------------------------- #


def test_health_check_is_reachable_without_a_token(authed_server):
    """Hosting platforms poll health before they hold any credentials."""
    response = httpx.get(f"{authed_server}/healthz", timeout=10)
    assert response.status_code == 200
    assert response.text == "ok"


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="no-header"),
        pytest.param({"Authorization": ""}, id="empty-header"),
        pytest.param({"Authorization": TOKEN}, id="missing-bearer-scheme"),
        # Note: "Bearer " with a trailing space is unsendable -- httpx rejects it
        # client-side as an illegal header value -- so the bare scheme stands in.
        pytest.param({"Authorization": "Bearer"}, id="bearer-scheme-only"),
        pytest.param({"Authorization": "Bearer wrong-token"}, id="wrong-token"),
        pytest.param({"Authorization": f"Bearer {TOKEN}x"}, id="token-with-suffix"),
        pytest.param({"Authorization": f"Bearer {TOKEN[:-1]}"}, id="token-truncated"),
        pytest.param({"Authorization": f"Basic {TOKEN}"}, id="wrong-scheme"),
    ],
)
def test_every_near_miss_is_rejected(authed_server, headers):
    response = httpx.post(
        f"{authed_server}/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers=headers,
        timeout=10,
    )
    assert response.status_code == 401
    # The refusal says nothing a caller could iterate on.
    assert response.json() == {"error": "unauthorized"}


def test_401_advertises_the_scheme(authed_server):
    response = httpx.post(
        f"{authed_server}/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        timeout=10,
    )
    assert response.status_code == 401
    assert "bearer" in response.headers.get("www-authenticate", "").lower()


def test_bearer_scheme_is_case_insensitive(authed_server):
    """RFC 7235 says the scheme is case-insensitive; clients vary."""
    for scheme in ("Bearer", "bearer", "BEARER"):
        response = httpx.post(
            f"{authed_server}/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Authorization": f"{scheme} {TOKEN}"},
            timeout=10,
        )
        assert response.status_code != 401, f"{scheme!r} was rejected"


# --------------------------------------------------------------------------- #
# Real MCP over HTTP
# --------------------------------------------------------------------------- #


def test_full_mcp_handshake_over_http(authed_server):
    """Same three tools, same eleven notes, same search-then-read flow."""
    from mcp import ClientSession
    # streamablehttp_client is the deprecated spelling; this is the current one.
    from mcp.client.streamable_http import streamable_http_client

    async def talk():
        # The current client takes a configured httpx client rather than a
        # `headers` kwarg (that was the deprecated streamablehttp_client), so the
        # bearer token rides on the HTTP client itself.
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {TOKEN}"}, timeout=30
        ) as http_client:
          async with streamable_http_client(
              f"{authed_server}/mcp", http_client=http_client
          ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await asyncio.wait_for(session.initialize(), 30)
                tools = sorted(t.name for t in (await session.list_tools()).tools)
                resources = (await session.list_resources()).resources
                found = await session.call_tool(
                    "search_notes", {"query": "resources vs tools"}
                )
                text = found.content[0].text
                uri = next(
                    line for line in text.splitlines() if "notes:///" in line
                ).split("uri:")[-1].strip()
                body = (await session.read_resource(uri)).contents[0].text
                refused = await session.call_tool(
                    "read_note", {"path": "../../etc/passwd"}
                )
                return tools, resources, text, uri, body, refused.content[0].text

    tools, resources, text, uri, body, refused = asyncio.run(talk())

    assert tools == ["list_notes", "read_note", "search_notes"]
    assert len(resources) == 11
    assert "notes:///" in text
    assert uri.startswith("notes:///")
    assert len(body) > 500
    # The containment boundary is a property of the server, not the transport.
    assert refused.startswith("Cannot read that note: ")
    assert "outside the notes folder" in refused


# --------------------------------------------------------------------------- #
# The deliberate opt-out
# --------------------------------------------------------------------------- #


def test_allow_no_auth_serves_openly_but_says_so():
    """Escape hatch for content you would publish anyway -- and it is noisy."""
    port = free_port()
    proc = spawn({"ALLOW_NO_AUTH": "1"}, port)
    try:
        assert await_health(proc, port), "open server did not come up"
        response = httpx.post(
            f"http://127.0.0.1:{port}/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            timeout=10,
        )
        assert response.status_code != 401
    finally:
        err = terminate(proc)

    assert "NO authentication" in err


# --------------------------------------------------------------------------- #
# Secret-in-the-URL mode (for clients that accept only a URL)
# --------------------------------------------------------------------------- #


def test_url_secret_moves_the_endpoint_and_gates_on_the_path():
    """`NOTES_URL_SECRET` serves at /mcp/<secret>; plain /mcp must 404.

    This is the mode that works with a UI offering nothing but a URL field. The
    secret is the credential, so the un-secreted path must not answer at all.
    """
    secret = "Zt7Qw2rLp9xK4mN8vB3sH6jD"
    port = free_port()
    proc = spawn({"NOTES_URL_SECRET": secret}, port)
    try:
        assert await_health(proc, port), "server did not come up"
        base = f"http://127.0.0.1:{port}"
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}

        assert httpx.post(f"{base}/mcp", json=body, timeout=10).status_code == 404
        assert httpx.post(f"{base}/mcp/wrong-secret", json=body, timeout=10).status_code == 404
        # The real path is reachable with no Authorization header at all.
        assert httpx.post(f"{base}/mcp/{secret}", json=body, timeout=10).status_code != 404
        assert httpx.get(f"{base}/healthz", timeout=10).status_code == 200
    finally:
        err = terminate(proc)

    assert "secret in URL path" in err


def test_url_secret_and_bearer_token_can_be_combined():
    """Both mechanisms at once: right path *and* right header required."""
    secret = "qP4nX8vT2wL6yG9bR3mCzK5d"
    port = free_port()
    proc = spawn({"NOTES_URL_SECRET": secret, "NOTES_TOKEN": TOKEN}, port)
    try:
        assert await_health(proc, port), "server did not come up"
        url = f"http://127.0.0.1:{port}/mcp/{secret}"
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}

        assert httpx.post(url, json=body, timeout=10).status_code == 401
        ok = httpx.post(
            url, json=body, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=10
        )
        assert ok.status_code != 401
    finally:
        err = terminate(proc)

    assert "bearer token" in err and "secret in URL path" in err
