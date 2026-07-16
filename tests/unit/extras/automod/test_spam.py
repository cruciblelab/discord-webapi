from types import SimpleNamespace

from discord_webapi.extras.automod.spam import make_check

GUILD_ID = 1
CHANNEL_ID = 2
USER_ID = 3


def _msg() -> SimpleNamespace:
    return SimpleNamespace(
        guild=SimpleNamespace(id=GUILD_ID),
        channel=SimpleNamespace(id=CHANNEL_ID),
        author=SimpleNamespace(id=USER_ID),
    )


def test_none_threshold_disables_the_check() -> None:
    assert make_check(threshold=None) is None


def test_stays_quiet_under_the_threshold() -> None:
    check = make_check(threshold=3, window_seconds=60.0)
    assert check is not None

    for _ in range(3):
        assert check(_msg()) is None  # type: ignore[arg-type]


def test_flags_once_over_the_threshold() -> None:
    check = make_check(threshold=2, window_seconds=60.0)
    assert check is not None

    assert check(_msg()) is None  # type: ignore[arg-type]
    assert check(_msg()) is None  # type: ignore[arg-type]
    assert check(_msg()) is not None  # type: ignore[arg-type]


def test_different_users_have_independent_windows() -> None:
    check = make_check(threshold=1, window_seconds=60.0)
    assert check is not None

    def msg(user_id: int) -> SimpleNamespace:
        return SimpleNamespace(
            guild=SimpleNamespace(id=GUILD_ID),
            channel=SimpleNamespace(id=CHANNEL_ID),
            author=SimpleNamespace(id=user_id),
        )

    assert check(msg(1)) is None  # type: ignore[arg-type]
    assert check(msg(2)) is None  # type: ignore[arg-type]
