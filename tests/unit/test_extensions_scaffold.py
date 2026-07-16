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
