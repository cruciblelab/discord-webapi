"""Google reCAPTCHA (v2 checkbox) as a `CaptchaProvider`. No local
challenge/answer state -- Google holds that. `issue()` just returns your
`site_key` for the frontend widget to render; `verify()` posts the
widget's response token to Google's own `siteverify` endpoint. Needs only
`httpx`, already a core dependency -- no extra install required.
"""

from __future__ import annotations

import httpx

from discord_webapi.captcha.models import CaptchaChallenge

_VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"


class ReCaptchaProvider:
    """Get `site_key`/`secret_key` from
    https://www.google.com/recaptcha/admin. Embed reCAPTCHA's own JS
    (`https://www.google.com/recaptcha/api.js`) plus a
    `<div class="g-recaptcha" data-sitekey="...">` on your page using the
    `site_key` this returns -- this class only handles server-side
    verification, it doesn't render or serve Google's widget itself.
    """

    kind = "recaptcha"

    def __init__(
        self,
        *,
        site_key: str,
        secret_key: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.site_key = site_key
        self._secret_key = secret_key
        self._external_http_client = http_client

    async def issue(self) -> CaptchaChallenge:
        # No server-side challenge state to create -- Google's widget IS
        # the challenge. challenge_id is unused by verify() below (kept
        # only so this satisfies the same CaptchaProvider shape as every
        # self-hosted provider); real state lives entirely with Google.
        return CaptchaChallenge(
            challenge_id=self.site_key,
            kind=self.kind,
            prompt="Complete the reCAPTCHA challenge.",
            site_key=self.site_key,
        )

    async def verify(self, challenge_id: str, response: str) -> bool:
        client = self._external_http_client or httpx.AsyncClient()
        try:
            resp = await client.post(
                _VERIFY_URL, data={"secret": self._secret_key, "response": response}
            )
            resp.raise_for_status()
            return bool(resp.json().get("success"))
        except httpx.HTTPError:
            return False
        finally:
            if self._external_http_client is None:
                await client.aclose()
