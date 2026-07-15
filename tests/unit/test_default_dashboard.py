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


def test_cookie_consent_banner_is_absent_by_default() -> None:
    app = FastAPI()
    app.include_router(build_default_dashboard_router())
    client = TestClient(app)

    resp = client.get("/")

    assert 'id="cookie-consent-banner"' not in resp.text
    assert "/api/consent" not in resp.text


def test_cookie_consent_banner_is_included_when_enabled() -> None:
    app = FastAPI()
    app.include_router(build_default_dashboard_router(enable_cookie_consent=True))
    client = TestClient(app)

    resp = client.get("/")

    assert 'id="cookie-consent-banner"' in resp.text
    assert "/api/consent" in resp.text


def test_cookie_consent_message_and_version_are_customizable() -> None:
    app = FastAPI()
    app.include_router(
        build_default_dashboard_router(
            enable_cookie_consent=True,
            cookie_consent_message="We use one cookie, deal with it.",
            cookie_consent_version="42",
        )
    )
    client = TestClient(app)

    resp = client.get("/")

    assert "We use one cookie, deal with it." in resp.text
    assert 'COOKIE_CONSENT_VERSION = "42"' in resp.text
