from types import SimpleNamespace

from discord_webapi.extras.automod.caps_spam import make_check


def _msg(content: str) -> SimpleNamespace:
    return SimpleNamespace(content=content)


def test_none_ratio_disables_the_check() -> None:
    assert make_check(ratio=None) is None


def test_short_message_never_flagged_even_if_all_caps() -> None:
    check = make_check(ratio=0.7, min_length=10)
    assert check is not None

    assert check(_msg("NO")) is None  # type: ignore[arg-type]


def test_flags_a_long_all_caps_message() -> None:
    check = make_check(ratio=0.7, min_length=10)
    assert check is not None

    assert check(_msg("THIS IS DEFINITELY SHOUTING AT EVERYONE HERE")) is not None  # type: ignore[arg-type]


def test_normal_sentence_case_passes() -> None:
    check = make_check(ratio=0.7, min_length=10)
    assert check is not None

    assert check(_msg("This is a normal sentence written politely.")) is None  # type: ignore[arg-type]


def test_only_alphabetic_characters_count_toward_the_ratio() -> None:
    check = make_check(ratio=0.5, min_length=5)
    assert check is not None
    # Lots of digits/punctuation, few (lowercase) letters -- must not be
    # flagged just because the whole string "looks aggressive".
    assert check(_msg("12345 67890 !!! abcde")) is None  # type: ignore[arg-type]
