from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

_DASHBOARD_HTML_TEMPLATE = (Path(__file__).parent / "dashboard.html").read_text()

DEFAULT_COOKIE_CONSENT_MESSAGE = (
    "This site uses a cookie to keep you signed in. "
    "By continuing to use it, you agree to that."
)
DEFAULT_COOKIE_CONSENT_VERSION = "1"

_BANNER_MARKUP = """  <div id="cookie-consent-banner" style="display:none">
    <p id="cookie-consent-message"></p>
    <button id="cookie-consent-accept-btn">Accept</button>
  </div>
"""

# Best-effort only, same spirit as builtins._shared.notify_member_best_effort:
# an anonymous (not-yet-logged-in) visitor has no session for the /api/consent
# endpoint to attach to, so the banner falls back to localStorage until they
# log in, then also records consent server-side via POST /api/consent.
_BANNER_SCRIPT = """
const COOKIE_CONSENT_VERSION = "{consent_version}";
const COOKIE_CONSENT_MESSAGE = {consent_message_json};
const consentLocalKey = "dwa_cookie_consent_dismissed_v" + COOKIE_CONSENT_VERSION;

async function checkCookieConsent() {{
  const banner = document.getElementById("cookie-consent-banner");
  document.getElementById("cookie-consent-message").textContent = COOKIE_CONSENT_MESSAGE;

  if (localStorage.getItem(consentLocalKey)) {{
    return;
  }}

  try {{
    const res = await fetch("/api/consent");
    if (res.status === 200) {{
      const record = await res.json();
      if (record && record.consent_version === COOKIE_CONSENT_VERSION) {{
        localStorage.setItem(consentLocalKey, "1");
        return;
      }}
    }}
  }} catch (e) {{
    // Not logged in yet, or the request failed -- fall through to showing
    // the banner; consent still gets recorded server-side once possible.
  }}

  banner.style.display = "flex";
}}

document.getElementById("cookie-consent-accept-btn").addEventListener("click", async () => {{
  localStorage.setItem(consentLocalKey, "1");
  document.getElementById("cookie-consent-banner").style.display = "none";
  try {{
    await fetch("/api/consent", {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ consent_version: COOKIE_CONSENT_VERSION }}),
    }});
  }} catch (e) {{
    // Not logged in -- the localStorage dismissal above is enough for now;
    // once they do log in and revisit, this runs again and persists it.
  }}
}});

checkCookieConsent();
"""


def build_default_dashboard_router(
    *,
    enable_cookie_consent: bool = False,
    cookie_consent_message: str = DEFAULT_COOKIE_CONSENT_MESSAGE,
    cookie_consent_version: str = DEFAULT_COOKIE_CONSENT_VERSION,
) -> APIRouter:
    """A minimal, self-contained (no build step, plain fetch()) dashboard:
    login link, a guild ID field, and a member table. Mounted at `/` and
    `/dashboard` by `DiscordWebAPI.install(app)` unless
    `serve_dashboard=False` -- pass that and mount your own UI instead once
    you outgrow this one; it exists to make `pip install discord-webapi`
    produce something clickable immediately, not to be a real product UI.

    `enable_cookie_consent` (only meaningful alongside
    `DiscordWebAPI.install(enable_cookie_consent=True)`, which mounts
    `GET/POST /api/consent`) adds a bottom banner with an Accept button.
    The message text is entirely yours to set via `cookie_consent_message`
    -- this library never dictates notice copy, only offers a place to
    show one and record that it was seen. Bump `cookie_consent_version`
    whenever the notice text changes to make everyone re-acknowledge it.
    """
    if enable_cookie_consent:
        banner_html = _BANNER_MARKUP
        banner_script = _BANNER_SCRIPT.format(
            consent_version=cookie_consent_version,
            consent_message_json=json.dumps(cookie_consent_message),
        )
    else:
        banner_html = ""
        banner_script = ""

    dashboard_html = _DASHBOARD_HTML_TEMPLATE.replace(
        "<!--COOKIE_CONSENT_BANNER-->", banner_html
    ).replace("/*COOKIE_CONSENT_SCRIPT*/", banner_script)

    router = APIRouter(include_in_schema=False)

    @router.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return dashboard_html

    @router.get("/dashboard", response_class=HTMLResponse)
    async def dashboard() -> str:
        return dashboard_html

    return router
