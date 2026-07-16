import pytest

from discord_webapi.extensions import (
    DiscoveredExtension,
    Extension,
    ExtensionManifest,
    ExtensionRegistry,
)
from discord_webapi.extensions import registry as registry_module


def _make_extension(name: str, *, requires: str | None = None) -> Extension:
    return Extension(
        manifest=ExtensionManifest(name=name, version="1.0.0", discord_webapi_requires=requires),
        setup=lambda bot, **kw: None,
    )


class _FakeEntryPoint:
    """Stand-in for importlib.metadata.EntryPoint."""

    def __init__(self, name: str, loads_to: object, *, raises: Exception | None = None) -> None:
        self.name = name
        self._loads_to = loads_to
        self._raises = raises

    def load(self) -> object:
        if self._raises is not None:
            raise self._raises
        return self._loads_to


# -- ExtensionManifest --


def test_manifest_minimal_fields() -> None:
    m = ExtensionManifest(name="funbot", version="1.0.0")
    assert m.name == "funbot"
    assert m.discord_webapi_requires is None
    assert m.provides == []


# -- _check_compatible --


def test_compatible_when_no_constraint() -> None:
    assert registry_module._check_compatible(None) == (True, None)


def test_compatible_when_version_in_range() -> None:
    ok, reason = registry_module._check_compatible(">=0.1,<1.0")
    assert ok is True
    assert reason is None


def test_incompatible_when_version_out_of_range() -> None:
    ok, reason = registry_module._check_compatible(">=99.0")
    assert ok is False
    assert "needs discord-webapi" in reason


def test_invalid_specifier_is_incompatible() -> None:
    ok, reason = registry_module._check_compatible("not-a-specifier")
    assert ok is False
    assert "invalid" in reason


# -- ExtensionRegistry basic ops --


def test_get_returns_the_extension() -> None:
    ext = DiscoveredExtension(_make_extension("a"), entry_point_name="a", compatible=True)
    reg = ExtensionRegistry([ext], [])

    assert reg.get("a").extension.manifest.name == "a"
    assert reg.names == ["a"]


def test_get_unknown_raises_with_helpful_message() -> None:
    reg = ExtensionRegistry([], [])
    with pytest.raises(KeyError, match="none installed"):
        reg.get("missing")


def test_list_only_compatible_filters() -> None:
    good = DiscoveredExtension(_make_extension("good"), entry_point_name="good", compatible=True)
    bad = DiscoveredExtension(
        _make_extension("bad"), entry_point_name="bad", compatible=False, compat_reason="nope"
    )
    reg = ExtensionRegistry([good, bad], [])

    assert [e.extension.manifest.name for e in reg.list()] == ["bad", "good"]
    assert [e.extension.manifest.name for e in reg.list(only_compatible=True)] == ["good"]


# -- _load_one --


def test_load_one_accepts_a_valid_extension() -> None:
    ext = _make_extension("funbot")
    ep = _FakeEntryPoint("funbot_ep", ext)
    errors: list = []

    result = ExtensionRegistry._load_one(ep, {}, errors)  # type: ignore[arg-type]

    assert result is not None
    assert result.extension is ext
    assert result.compatible is True
    assert errors == []


def test_load_one_rejects_wrong_type() -> None:
    ep = _FakeEntryPoint("bogus", object())  # not an Extension
    errors: list = []

    result = ExtensionRegistry._load_one(ep, {}, errors)  # type: ignore[arg-type]

    assert result is None
    assert len(errors) == 1
    assert "not a" in errors[0].message


def test_load_one_records_import_failure() -> None:
    ep = _FakeEntryPoint("boom", None, raises=RuntimeError("kaboom"))
    errors: list = []

    result = ExtensionRegistry._load_one(ep, {}, errors)  # type: ignore[arg-type]

    assert result is None
    assert "failed to import" in errors[0].message


def test_load_one_rejects_duplicate_name() -> None:
    ep = _FakeEntryPoint("second", _make_extension("dup"))
    seen = {"dup": "first"}
    errors: list = []

    result = ExtensionRegistry._load_one(ep, seen, errors)  # type: ignore[arg-type]

    assert result is None
    assert "duplicate" in errors[0].message


# -- discover() with a monkeypatched entry-point group --


def test_discover_reads_the_entry_point_group(monkeypatch: pytest.MonkeyPatch) -> None:
    ext = _make_extension("funbot")
    broken = _FakeEntryPoint("broken", None, raises=ValueError("bad"))

    def fake_entry_points(*, group: str) -> list:
        assert group == registry_module.ENTRY_POINT_GROUP
        return [_FakeEntryPoint("funbot_ep", ext), broken]

    monkeypatch.setattr(registry_module, "entry_points", fake_entry_points)

    reg = ExtensionRegistry.discover()

    assert reg.names == ["funbot"]
    assert reg.get("funbot").extension is ext
    assert len(reg.errors) == 1
    assert reg.errors[0].entry_point_name == "broken"


def test_discover_incompatible_extension_is_listed_but_flagged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ext = _make_extension("oldext", requires=">=99.0")

    def fake_entry_points(*, group: str) -> list:
        return [_FakeEntryPoint("oldext_ep", ext)]

    monkeypatch.setattr(registry_module, "entry_points", fake_entry_points)

    reg = ExtensionRegistry.discover()

    d = reg.get("oldext")
    assert d.compatible is False
    assert reg.list(only_compatible=True) == []


def test_sdk_exposes_the_public_surface() -> None:
    from discord_webapi.extensions import sdk

    for name in ("GuildRateLimiter", "EscalationEngine", "rate_limited", "Extension"):
        assert name in sdk.__all__
        assert hasattr(sdk, name)
