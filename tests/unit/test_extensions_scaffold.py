from pathlib import Path

import pytest

from discord_webapi.extensions import scaffold


def test_sanitize_pkg_makes_a_valid_identifier() -> None:
    assert scaffold._sanitize_pkg("Fun Bot") == "fun_bot"
    assert scaffold._sanitize_pkg("my-cool.ext") == "my_cool_ext"
    assert scaffold._sanitize_pkg("123abc").startswith("ext_")


def test_create_extension_writes_the_expected_tree(tmp_path: Path) -> None:
    root = scaffold.create_extension("funbot", tmp_path)

    assert root == tmp_path / "funbot"
    assert (root / "pyproject.toml").is_file()
    assert (root / "funbot" / "__init__.py").is_file()
    assert (root / "funbot" / "commands.py").is_file()
    assert (root / "tests" / "test_funbot.py").is_file()
    assert (root / "README.md").is_file()


def test_generated_pyproject_declares_the_entry_point(tmp_path: Path) -> None:
    root = scaffold.create_extension("funbot", tmp_path)
    pyproject = (root / "pyproject.toml").read_text()

    assert '[project.entry-points."discord_webapi.extensions"]' in pyproject
    assert 'funbot = "funbot:extension"' in pyproject
    assert 'asyncio_mode = "auto"' in pyproject


def test_generated_init_builds_an_extension_object(tmp_path: Path) -> None:
    root = scaffold.create_extension("funbot", tmp_path)
    init = (root / "funbot" / "__init__.py").read_text()

    assert "from discord_webapi.extensions.sdk import Extension, ExtensionManifest" in init
    assert 'name="funbot"' in init
    assert "extension = Extension(" in init


def test_generated_command_f_string_braces_survive_templating(tmp_path: Path) -> None:
    """Regression: the templating must not mangle the generated f-string's
    own braces (it uses token replacement, not str.format, for this reason)."""
    root = scaffold.create_extension("funbot", tmp_path)
    commands = (root / "funbot" / "commands.py").read_text()

    assert "{random.randint(1, 6)}" in commands
    assert "__PKG__" not in commands  # all tokens replaced


def test_create_extension_refuses_to_overwrite(tmp_path: Path) -> None:
    scaffold.create_extension("funbot", tmp_path)
    with pytest.raises(FileExistsError):
        scaffold.create_extension("funbot", tmp_path)


def test_dist_name_normalizes_underscores_and_spaces(tmp_path: Path) -> None:
    root = scaffold.create_extension("My Cool Ext", tmp_path)
    assert root.name == "my-cool-ext"
    # but the import package is a valid identifier
    assert (root / "my_cool_ext" / "__init__.py").is_file()


def test_cli_main_creates_and_reports(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = scaffold.main(["new", "funbot", "--dir", str(tmp_path)])

    assert rc == 0
    assert (tmp_path / "funbot").is_dir()
    out = capsys.readouterr().out
    assert "Created extension skeleton" in out


def test_cli_main_errors_on_existing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    scaffold.main(["new", "funbot", "--dir", str(tmp_path)])
    rc = scaffold.main(["new", "funbot", "--dir", str(tmp_path)])

    assert rc == 1
    assert "already exists" in capsys.readouterr().err


def test_relative_path_traversal_in_name_does_not_escape_target_dir(tmp_path: Path) -> None:
    """Regression test: `dist` (which becomes the actual `target_dir /
    dist` project root written to disk) used to be built from the raw
    name with only `_`/` ` replaced -- `..` and `/` passed straight
    through, so a name like "../../../etc/whatever" escaped `target_dir`
    entirely via normal `..` path traversal once the OS resolved it."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    escape_target = tmp_path / "escaped"

    root = scaffold.create_extension("../../escaped", workdir)

    assert not escape_target.exists()
    assert workdir.resolve() in root.resolve().parents


def test_absolute_path_in_name_does_not_escape_target_dir(tmp_path: Path) -> None:
    """Regression test: `Path("a") / "/etc/x"` discards "a" and becomes
    the absolute path outright -- a name that happened to look like an
    absolute path (e.g. "/tmp/whatever") used to make `create_extension`
    write completely outside `target_dir`, ignoring it altogether."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    absolute_evil = tmp_path / "definitely-not-workdir"

    root = scaffold.create_extension(str(absolute_evil), workdir)

    assert not absolute_evil.exists()
    assert workdir.resolve() in root.resolve().parents


def test_manifest_name_matches_the_sanitized_importable_package_name(tmp_path: Path) -> None:
    """Regression test: `ExtensionManifest.name` is documented as a
    "unique, importable-style short name ... used as the key in
    ExtensionRegistry.get(name)" -- the generated __init__.py used to set
    it to the *raw*, unsanitized input (e.g. "My Fun Bot!", with spaces/
    punctuation) instead of the sanitized package slug actually used for
    `from __PKG__.commands import setup`, so the manifest's own declared
    name didn't match its own importable package."""
    root = scaffold.create_extension("My Fun Bot!", tmp_path)
    pkg = scaffold._sanitize_pkg("My Fun Bot!")
    init = (root / pkg / "__init__.py").read_text()

    assert f'name="{pkg}"' in init
    assert "My Fun Bot!" not in init
