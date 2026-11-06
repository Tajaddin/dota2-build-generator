"""The FastAPI application: API routes, the GSI endpoint and the built UI on one port."""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from d2bg import __version__, paths
from d2bg.api import knowledge_routes, live_routes, player_routes
from d2bg.api.services import Services
from d2bg.context import AppContext

DEFAULT_PORT = 4242
LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}
# The names this computer's own browser and Dota use. Any other Host on a loopback connection may be a
# web page that rebound its own domain to 127.0.0.1, so it is treated like another device.
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

NOT_BUILT = """<!doctype html><html><head><meta charset="utf-8"><title>d2bg</title></head>
<body style="font-family:system-ui;background:#111;color:#eee;padding:2rem">
<h1>The UI is not built yet</h1><p>Run <code>.\\run.cmd</code>, or <code>npm ci &amp;&amp; npm run build</code>
in <code>web/</code>. The API is up: <a style="color:#8cf" href="/docs">/docs</a>.</p></body></html>"""


def _host_name(host: str) -> str:
    """The Host header without its port: ``[::1]:4242`` -> ``[::1]``."""
    host = host.lower()
    return host if host.endswith("]") else host.rsplit(":", 1)[0]


def _cross_origin(request: Request) -> bool:
    """A browser sent this from a page on another origin. Requests without Origin (Dota, curl) pass."""
    origin = request.headers.get("origin")
    return origin is not None and urlsplit(origin.lower()).netloc != request.headers.get("host", "").lower()


def create_app(
    ctx: AppContext | None = None, port: int = DEFAULT_PORT, lan: bool = False, static_dir: Path | None = None
) -> FastAPI:
    context = ctx or AppContext()
    svc = Services(context, port)
    dist = static_dir or paths.web_dist_dir()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        svc.close()

    app = FastAPI(
        title="d2bg",
        version=__version__,
        lifespan=lifespan,
        description="Dota 2 companion: GSI, public data, no game modification.",
    )
    app.state.services = svc

    @app.middleware("http")
    async def lan_guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """Other devices (LAN mode) must present the LAN token; this computer, addressed by a localhost
        name, never needs one. Writes sent by pages on other origins are refused."""
        if request.method not in SAFE_METHODS and _cross_origin(request):
            return JSONResponse({"detail": "Requests from other websites are refused"}, status_code=403)
        client = request.client.host if request.client else ""
        if client not in LOOPBACK or _host_name(request.headers.get("host", "")) not in LOCAL_HOSTS:
            settings = context.settings.get()
            token = (
                request.query_params.get("token")
                or request.headers.get("x-d2bg-token")
                or request.cookies.get("d2bg_token")
                or ""
            )
            if not lan or not hmac.compare_digest(token, settings.lan_token):
                return JSONResponse({"detail": "LAN access needs the token from Settings"}, status_code=403)
            response = await call_next(request)
            response.set_cookie("d2bg_token", settings.lan_token, httponly=True, samesite="strict")
            return response
        return await call_next(request)

    @app.get("/health", include_in_schema=False)
    def health() -> dict[str, object]:
        return {"ok": True, "version": __version__}

    app.include_router(live_routes.router)
    app.include_router(knowledge_routes.router)
    app.include_router(player_routes.router)

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> Response:
        if full_path.startswith(("api/", "gsi")):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        if not (dist / "index.html").is_file():
            return HTMLResponse(NOT_BUILT)
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")

    return app
