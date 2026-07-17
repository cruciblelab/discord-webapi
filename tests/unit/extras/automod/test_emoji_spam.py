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


def test_flag_emoji_count_once_not_twice() -> None:
    """Regression test: a flag emoji (e.g. the US flag) is two REGIONAL
    INDICATOR SYMBOL codepoints forming a single glyph -- matching each
    codepoint separately double-counted every flag."""
    check = make_check(max_emoji=3)
    assert check is not None

    us_flag = "\U0001f1fa\U0001f1f8"
    three_flags = " ".join([us_flag] * 3)
    assert check(_msg(three_flags)) is None  # type: ignore[arg-type]

    four_flags = " ".join([us_flag] * 4)
    assert check(_msg(four_flags)) is not None  # type: ignore[arg-type]


def test_skin_toned_emoji_count_once_not_twice() -> None:
    """Regression test: a skin-toned emoji is a base codepoint plus one
    EMOJI MODIFIER FITZPATRICK codepoint forming a single glyph --
    matching each codepoint separately double-counted every one."""
    check = make_check(max_emoji=3)
    assert check is not None

    thumbs_up_medium = "\U0001f44d\U0001f3fd"
    three = " ".join([thumbs_up_medium] * 3)
    assert check(_msg(three)) is None  # type: ignore[arg-type]

    four = " ".join([thumbs_up_medium] * 4)
    assert check(_msg(four)) is not None  # type: ignore[arg-type]
