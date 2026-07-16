from types import SimpleNamespace

from discord_webapi.builtins.automod.mention_spam import make_check


def _msg(*, mentions: int = 0, role_mentions: int = 0, everyone: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        mentions=[object()] * mentions,
        role_mentions=[object()] * role_mentions,
        mention_everyone=everyone,
    )


def test_none_max_disables_the_check() -> None:
    assert make_check(max_mentions=None) is None


def test_stays_quiet_under_the_limit() -> None:
    check = make_check(max_mentions=5)
    assert check is not None

    assert check(_msg(mentions=3)) is None  # type: ignore[arg-type]


def test_flags_over_the_limit() -> None:
    check = make_check(max_mentions=5)
    assert check is not None

    assert check(_msg(mentions=6)) is not None  # type: ignore[arg-type]


def test_counts_user_and_role_mentions_together() -> None:
    check = make_check(max_mentions=5)
    assert check is not None

    assert check(_msg(mentions=3, role_mentions=3)) is not None  # type: ignore[arg-type]


def test_mention_everyone_counts_as_one() -> None:
    check = make_check(max_mentions=0)
    assert check is not None

    assert check(_msg(everyone=True)) is not None  # type: ignore[arg-type]
    assert check(_msg(everyone=False)) is None  # type: ignore[arg-type]
