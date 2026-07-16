from types import SimpleNamespace

from discord_webapi.builtins.automod.invite_filter import make_check


def _msg(content: str) -> SimpleNamespace:
    return SimpleNamespace(content=content)


def test_disabled_by_default() -> None:
    assert make_check(enabled=False) is None


def test_flags_a_discord_gg_invite() -> None:
    check = make_check(enabled=True)
    assert check is not None

    assert check(_msg("join us! discord.gg/abc123")) is not None  # type: ignore[arg-type]


def test_flags_a_discord_com_invite_link() -> None:
    check = make_check(enabled=True)
    assert check is not None

    assert check(_msg("https://discord.com/invite/abc123")) is not None  # type: ignore[arg-type]


def test_allowlisted_code_is_not_flagged() -> None:
    check = make_check(enabled=True, allowed_codes=["abc123"])
    assert check is not None

    assert check(_msg("discord.gg/abc123")) is None  # type: ignore[arg-type]


def test_message_without_an_invite_passes() -> None:
    check = make_check(enabled=True)
    assert check is not None

    assert check(_msg("hello there")) is None  # type: ignore[arg-type]
