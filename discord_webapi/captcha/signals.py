"""Ready-made `PredicateCheck`s for client *instrumentation* signals -- the
"is this a real browser" half of an invisible layer (the other half being
`ProofOfWorkProvider`).

Be clear-eyed about what this is. Browser instrumentation -- reading
`navigator.webdriver`, event timings, pointer entropy, and so on -- happens
in the client's JavaScript, which you write and which the client can lie
about. The server can only receive whatever the client chose to send (in
the gate verify request's `signals` bag) and apply a *transparent* rule to
it. These helpers are exactly that: small, honest, easily-bypassed rules --
a speed bump against low-effort automation, not a bot detector. Anything
that claims to reliably tell a human from a bot purely server-side from
client-submitted signals is lying to you.

Use them as one cheap layer in a gate, alongside proof-of-work (real cost)
and account binding (real identity):

    gate = CaptchaGate(
        transport, store,
        require_captcha=False,
        extra_checks=[reject_webdriver(), require_min_interaction_ms(400)],
    )

...and write your own `PredicateCheck` for anything more sophisticated
(your own fingerprint scoring, an external anti-fraud service, ...).
"""

from __future__ import annotations

from discord_webapi.captcha.checks import CheckOutcome, PredicateCheck, VerificationContext


def reject_webdriver(name: str = "no-webdriver") -> PredicateCheck:
    """Fails if the client reported `navigator.webdriver === true`
    (`signals["webdriver"]`). Trivially spoofable -- an automated browser
    can just not send it -- but it's free and catches the laziest tools."""

    async def _check(ctx: VerificationContext) -> CheckOutcome:
        if ctx.signals.get("webdriver") is True:
            return CheckOutcome(False, "navigator.webdriver was true")
        return CheckOutcome(True)

    return PredicateCheck(name, _check)


def require_signal_flag(flag: str, *, name: str | None = None) -> PredicateCheck:
    """Fails unless the client sent `signals[flag] is True`. Use for your
    own client-side attestation ("passed my JS instrumentation") -- again,
    only as trustworthy as your JS and the fact the client can forge it."""

    async def _check(ctx: VerificationContext) -> CheckOutcome:
        if ctx.signals.get(flag) is True:
            return CheckOutcome(True)
        return CheckOutcome(False, f"required signal {flag!r} was not set")

    return PredicateCheck(name or f"signal-{flag}", _check)


def require_min_interaction_ms(minimum_ms: int, *, name: str = "min-interaction") -> PredicateCheck:
    """Fails if the client-reported interaction time
    (`signals["interaction_ms"]`) is under `minimum_ms` -- a form solved in
    3ms is suspicious. Spoofable (the client picks the number), so it's a
    heuristic, not a gate on its own."""

    async def _check(ctx: VerificationContext) -> CheckOutcome:
        value = ctx.signals.get("interaction_ms")
        if isinstance(value, int | float) and value >= minimum_ms:
            return CheckOutcome(True)
        return CheckOutcome(False, f"interaction was faster than {minimum_ms}ms (or not reported)")

    return PredicateCheck(name, _check)
