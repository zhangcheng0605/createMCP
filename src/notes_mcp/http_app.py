"""HTTP transport for notes-mcp: the same notes, reachable at a URL.

``server.py`` serves the notes over **stdio** -- a client launches the server as a
child process and talks over pipes. That is the right shape for a personal vault
on your own laptop, and it needs no auth because there is no network involved.

This module serves the *same* ``FastMCP`` app over **Streamable HTTP** instead, so
a remote client (claude.ai's "Add custom connector", which asks for a URL) can
reach it. Nothing about the tools or resources changes -- only the transport.

That change moves the security boundary, though, and this module is mostly about
that:

* On stdio, the only thing that can reach the server is the process that spawned
  it. On HTTP, the only thing standing between your notes and the open internet
  is whatever check this module performs. So a bearer token is **required** by
  default; the server refuses to start without one rather than quietly serving
  your notes to anyone who finds the URL.
* The notes have to live wherever the server runs. Publishing a folder here means
  copying it to that host. Think about which notes those are.
"""

from __future__ import annotations

import hmac
import os
import secrets

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

#: Paths served without a token. Hosting platforms poll a health endpoint before
#: they have any credentials, and a 401 there looks like a dead deploy.
PUBLIC_PATHS = frozenset({"/healthz", "/"})


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Require ``Authorization: Bearer <token>`` on everything but health checks.

    The comparison uses :func:`hmac.compare_digest` rather than ``==``. String
    equality in Python returns as soon as two bytes differ, so how long a
    rejection takes leaks how much of the prefix was right -- enough, over many
    requests, to guess a token one character at a time. ``compare_digest`` takes
    the same time whatever the input.
    """

    def __init__(self, app, token: str) -> None:
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        header = request.headers.get("authorization", "")
        scheme, _, presented = header.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(
            presented.strip(), self._token
        ):
            # No detail about *why* it failed: a client that does not already
            # have the token learns nothing it can iterate on.
            return JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="notes-mcp"'},
            )
        return await call_next(request)


async def _healthz(_request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


def resolve_auth() -> tuple[str | None, str | None]:
    """Work out how this server is protected. Returns ``(bearer, url_secret)``.

    Three mechanisms, because clients differ in what they can send:

    ``NOTES_TOKEN``
        A bearer token in the ``Authorization`` header. The strongest option and
        the right one for a client you control -- but many UIs that accept a
        remote MCP server ask only for a URL, with no field for a header. For
        those, use the next one.

    ``NOTES_URL_SECRET``
        Mounts the endpoint at ``/mcp/<secret>`` instead of ``/mcp``, so the URL
        *is* the credential (a "capability URL"). Weaker than a header: URLs get
        logged by proxies, land in browser history, and are easy to paste into
        the wrong window. But a long random one is far better than nothing, and
        it is the only thing that works when a URL field is all you have.

    ``ALLOW_NO_AUTH=1``
        Wide open. Only reasonable for notes you would publish anyway.

    Set none of them and the server refuses to start. Forgetting to configure
    auth is a much more likely accident than genuinely wanting to publish a
    personal vault, so the default has to be the one that fails loudly.
    """
    bearer = os.environ.get("NOTES_TOKEN", "").strip() or None
    url_secret = os.environ.get("NOTES_URL_SECRET", "").strip() or None
    opted_out = os.environ.get("ALLOW_NO_AUTH", "").strip() == "1"

    if bearer or url_secret or opted_out:
        return bearer, url_secret

    suggestion = secrets.token_urlsafe(32)
    raise SystemExit(
        "notes-mcp: refusing to serve over HTTP with no protection at all.\n"
        "  Header auth (strongest):  NOTES_TOKEN=" + suggestion + "\n"
        "  Secret in the URL:        NOTES_URL_SECRET=" + suggestion + "\n"
        "    (serves at /mcp/<secret> -- use this when a client only accepts a URL)\n"
        "  Or opt out loudly:        ALLOW_NO_AUTH=1  (anyone with the URL can read "
        "every note -- only do this for notes you would publish anyway)"
    )


def build_app(mcp, token: str | None) -> Starlette:
    """Wrap the FastMCP Streamable HTTP app with a health route and auth."""
    app: Starlette = mcp.streamable_http_app()
    app.router.routes.append(Route("/healthz", _healthz, methods=["GET"]))
    if token is not None:
        app.add_middleware(BearerTokenMiddleware, token=token)
    return app


def serve(mcp, log) -> None:
    """Serve ``mcp`` over Streamable HTTP until killed.

    Host and port come from ``HOST``/``PORT``; the defaults suit a container
    (``0.0.0.0``), and every hosting platform injects ``PORT`` itself. Unlike the
    stdio path there is no stdout discipline to keep here -- stdout is not a
    protocol channel over HTTP -- but logging stays on stderr so the two
    transports behave the same way.
    """
    import uvicorn

    bearer, url_secret = resolve_auth()
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))

    # Mounting under the secret has to happen before streamable_http_app() is
    # built, since that is when the route is created.
    if url_secret:
        mcp.settings.streamable_http_path = f"/mcp/{url_secret}"
    path = mcp.settings.streamable_http_path

    if not bearer and not url_secret:
        log("WARNING: serving with NO authentication (ALLOW_NO_AUTH=1)")
    else:
        log(
            "auth: "
            + ", ".join(
                filter(
                    None,
                    [
                        "bearer token" if bearer else None,
                        "secret in URL path" if url_secret else None,
                    ],
                )
            )
        )
    # The path is logged in full because it may contain the URL secret, and the
    # operator needs to know the address they just published. stderr only -- this
    # line must never end up in a screenshot of a shared terminal.
    log(f"listening on http://{host}:{port}{path} (health: /healthz)")

    uvicorn.run(
        build_app(mcp, bearer),
        host=host,
        port=port,
        log_level="info",
        access_log=False,
    )
