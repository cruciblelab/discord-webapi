from types import SimpleNamespace

import pytest

from discord_webapi.extras.automod.link_filter import make_check


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


def test_blocklist_is_not_bypassed_by_adding_a_port() -> None:
    """Regression test: the host-extraction regex used to capture a
    trailing `:port` as part of the "host" -- `"evil.com:8080"` matches
    neither `== "evil.com"` nor `.endswith(".evil.com")`, so tacking a
    port onto a blocked link let it straight through."""
    check = make_check(blocked_domains=["evil.com"])
    assert check is not None

    assert check(_msg("https://evil.com:8080/page")) is not None  # type: ignore[arg-type]
    assert check(_msg("https://evil.com:8080")) is not None  # type: ignore[arg-type]


def test_allowlist_does_not_false_flag_an_allowed_domain_with_a_port() -> None:
    check = make_check(allowed_domains=["good.com"])
    assert check is not None

    assert check(_msg("https://good.com:8080/page")) is None  # type: ignore[arg-type]


def test_blocklist_is_not_bypassed_by_dropping_the_scheme() -> None:
    """Regression test: the old regex only matched `https?://` -- a
    spammer (or Discord's own client, which hyperlinks bare/`www.`
    domains regardless of scheme) could bypass the entire filter just by
    not typing "https://"."""
    check = make_check(blocked_domains=["evil.com"])
    assert check is not None

    assert check(_msg("www.evil.com/free-nitro")) is not None  # type: ignore[arg-type]
    assert check(_msg("check out evil.com/free-nitro now")) is not None  # type: ignore[arg-type]


def test_allowlist_is_not_bypassed_by_dropping_the_scheme() -> None:
    check = make_check(allowed_domains=["good.com"])
    assert check is not None

    assert check(_msg("check out random-site.com/free-nitro")) is not None  # type: ignore[arg-type]


def test_ordinary_prose_mentioning_dotted_names_is_not_flagged() -> None:
    """The bare-domain (no scheme, no www.) branch requires a trailing
    `/path` to trigger -- otherwise ordinary tech talk ("we love node.js
    and vue.js") would constantly false-positive as a link."""
    check = make_check(blocked_domains=["evil.com"])
    assert check is not None

    assert check(_msg("we love node.js and vue.js frameworks")) is None  # type: ignore[arg-type]
    assert check(_msg("just mentioning evil.com in passing")) is None  # type: ignore[arg-type]
