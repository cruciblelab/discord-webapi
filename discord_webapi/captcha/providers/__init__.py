"""Captcha providers -- pluggable backends implementing
`discord_webapi.captcha.base.CaptchaProvider`. Two self-hosted (Math,
Text) and two third-party widget wrappers (reCAPTCHA, hCaptcha) ship
here; write your own for anything else (a different service, your own
challenge type) by implementing that same Protocol.
"""
