from types import SimpleNamespace

import pytest

from discord_webapi.builtins.automod.link_filter import make_check


def _msg(content: str) -> SimpleNamespace:
    return SimpleNamespace(content=content)


def test_neither_list_disables_the_check() -> None:
    assert make_check() is None


def test_both_lists_at_once_is_rejected() -> None:
    with pytest.raises(ValueError, match="not both"):
        make_check(allowed_domains=["example.com"], blocked_domains=["evil.com"])


def test_blocklist_flags_a_matching_domain() -> None:
    check = make_check(blocked_domains=["evil.com"])
    assert check is not None

    assert check(_msg("check this out https://evil.com/page")) is not None  # type: ignore[arg-type]


def test_blocklist_matches_subdomains() -> None:
    check = make_check(blocked_domains=["evil.com"])
    assert check is not None

    assert check(_msg("https://sub.evil.com/page")) is not None  # type: ignore[arg-type]


def test_blocklist_allows_unrelated_domains() -> None:
    check = make_check(blocked_domains=["evil.com"])
    assert check is not None

    assert check(_msg("https://example.com/page")) is None  # type: ignore[arg-type]


def test_allowlist_flags_anything_not_listed() -> None:
    check = make_check(allowed_domains=["example.com"])
    assert check is not None

    assert check(_msg("https://random-site.com")) is not None  # type: ignore[arg-type]


def test_allowlist_permits_listed_domains() -> None:
    check = make_check(allowed_domains=["example.com"])
    assert check is not None

    assert check(_msg("https://example.com/page")) is None  # type: ignore[arg-type]


def test_message_with_no_links_passes_either_mode() -> None:
    check = make_check(blocked_domains=["evil.com"])
    assert check is not None

    assert check(_msg("no links here")) is None  # type: ignore[arg-type]
