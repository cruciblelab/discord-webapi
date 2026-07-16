from types import SimpleNamespace

from discord_webapi.builtins.automod.banned_words import make_check


def _msg(content: str) -> SimpleNamespace:
    return SimpleNamespace(content=content)


def test_empty_word_list_disables_the_check() -> None:
    assert make_check([]) is None


def test_flags_a_banned_word() -> None:
    check = make_check(["badword"])
    assert check is not None

    assert check(_msg("this has a badword in it")) is not None  # type: ignore[arg-type]


def test_is_case_insensitive() -> None:
    check = make_check(["badword"])
    assert check is not None

    assert check(_msg("BADWORD is here")) is not None  # type: ignore[arg-type]


def test_matches_whole_words_only() -> None:
    check = make_check(["ass"])
    assert check is not None

    assert check(_msg("i study in class today")) is None  # type: ignore[arg-type]


def test_clean_message_passes() -> None:
    check = make_check(["badword"])
    assert check is not None

    assert check(_msg("hello, how are you?")) is None  # type: ignore[arg-type]
