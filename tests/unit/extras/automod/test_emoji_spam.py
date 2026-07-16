from types import SimpleNamespace

from discord_webapi.extras.automod.emoji_spam import make_check


def _msg(content: str) -> SimpleNamespace:
    return SimpleNamespace(content=content)


def test_none_max_disables_the_check() -> None:
    assert make_check(max_emoji=None) is None


def test_stays_quiet_under_the_limit() -> None:
    check = make_check(max_emoji=5)
    assert check is not None

    assert check(_msg("hello \U0001f600")) is None  # type: ignore[arg-type]


def test_flags_too_many_unicode_emoji() -> None:
    check = make_check(max_emoji=2)
    assert check is not None

    spammy = "\U0001f600" * 5
    assert check(_msg(spammy)) is not None  # type: ignore[arg-type]


def test_flags_too_many_custom_emoji() -> None:
    check = make_check(max_emoji=2)
    assert check is not None

    spammy = "<:pepe:123> <:pepe:123> <:pepe:123>"
    assert check(_msg(spammy)) is not None  # type: ignore[arg-type]


def test_message_without_emoji_passes() -> None:
    check = make_check(max_emoji=0)
    assert check is not None

    assert check(_msg("plain text, no emoji at all")) is None  # type: ignore[arg-type]
