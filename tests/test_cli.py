import re
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from podcleaner_clips import prog_name
from podcleaner_clips.cli import app


def test_version_command_prints_version():
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_unknown_command_is_a_usage_error_without_traceback():
    script = (
        "from podcleaner_clips.cli import main\n"
        "import sys; sys.argv = ['podcleaner-clips', 'nope']\n"
        "main()\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, encoding="utf-8"
    )
    assert proc.returncode == 2
    assert "nope" in proc.stderr
    assert "Traceback" not in proc.stdout + proc.stderr


def test_clips_error_exits_2_with_message():
    # Runs the real main() entry point in a subprocess, with a command
    # added for the test that raises ClipsError.
    script = (
        "from podcleaner_clips.cli import app, main\n"
        "from podcleaner_clips.errors import ClipsError\n"
        "@app.command('boom')\n"
        "def boom():\n"
        "    raise ClipsError('File not found: x.mkv')\n"
        "import sys; sys.argv = ['podcleaner-clips', 'boom']\n"
        "main()\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, encoding="utf-8"
    )
    assert proc.returncode == 2
    assert "Error: File not found: x.mkv" in proc.stderr
    assert "Traceback" not in proc.stdout + proc.stderr


def test_version_option():
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == "0.1.0"


def test_command_alone_shows_help_and_exits_0():
    result = CliRunner().invoke(app, [])
    assert result.exit_code == 0
    for command in ("init", "run", "config", "version"):
        assert command in result.output


def test_init_creates_the_config(tmp_path):
    cfg = tmp_path / "conf" / "config.toml"
    result = CliRunner().invoke(app, ["init", "--config", str(cfg)])
    assert result.exit_code == 0
    assert cfg.is_file()
    assert "episodes_dir" in cfg.read_text(encoding="utf-8")


def test_config_init_still_works(tmp_path):
    cfg = tmp_path / "config.toml"
    assert CliRunner().invoke(app, ["config", "init", "--config", str(cfg)]).exit_code == 0
    assert cfg.is_file()


def test_config_alone_shows_it_and_show_still_works(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('episodes_dir = "ep"\n', encoding="utf-8")
    for args in (["config"], ["config", "show"]):
        result = CliRunner().invoke(app, [*args, "--config", str(cfg)])
        assert result.exit_code == 0, result.output
        assert f"File: {cfg}" in result.output
        assert "episodes_dir = " in result.output


def test_config_path_prints_only_the_path(tmp_path):
    cfg = tmp_path / "config.toml"  # need not exist
    result = CliRunner().invoke(app, ["config", "--path", "--config", str(cfg)])
    assert result.exit_code == 0
    assert result.output.strip() == str(cfg)


def test_hidden_aliases_not_in_help():
    result = CliRunner().invoke(app, ["config", "--help"])
    assert re.search(r"\bshow\b", result.output) is None
    assert re.search(r"\binit\b", result.output) is None


@pytest.mark.parametrize(
    "argv0, name",
    [
        ("/usr/local/bin/pclips", "pclips"),
        (r"C:\Users\me\.local\bin\pclips.exe", "pclips"),
        ("/x/podcleaner-clips", "podcleaner-clips"),
        ("/x/python", "podcleaner-clips"),
        ("", "podcleaner-clips"),
    ],
)
def test_prog_name_is_the_name_typed(monkeypatch, argv0, name):
    monkeypatch.setattr(sys, "argv", [argv0])
    assert prog_name() == name


def test_usage_shows_pclips_when_typed():
    script = (
        "from podcleaner_clips.cli import main\n"
        "import sys; sys.argv = ['pclips', '--help']\n"
        "main()\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, encoding="utf-8"
    )
    assert "Usage: pclips" in proc.stdout
