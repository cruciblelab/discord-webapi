from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

_DASHBOARD_HTML = (Path(__file__).parent / "dashboard.html").read_text()


def build_default_dashboard_router() -> APIRouter:
    """A minimal, self-contained (no build step, plain fetch()) dashboard:
    login link, a guild ID field, and a member table. Mounted at `/` and
    `/dashboard` by `DiscordWebAPI.install(app)` unless
    `serve_dashboard=False` -- pass that and mount your own UI instead once
    you outgrow this one; it exists to make `pip install discord-webapi`
    produce something clickable immediately, not to be a real product UI.
    """
    router = APIRouter(include_in_schema=False)

    @router.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _DASHBOARD_HTML

    @router.get("/dashboard", response_class=HTMLResponse)
    async def dashboard() -> str:
        return _DASHBOARD_HTML

    return router
