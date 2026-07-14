from fastapi import FastAPI
from fastapi.testclient import TestClient

from discord_webapi.web import build_default_dashboard_router


def test_default_dashboard_serves_html_at_root_and_dashboard() -> None:
    app = FastAPI()
    app.include_router(build_default_dashboard_router())
    client = TestClient(app)

    for path in ("/", "/dashboard"):
        resp = client.get(path)
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        assert "discord-webapi" in resp.text
