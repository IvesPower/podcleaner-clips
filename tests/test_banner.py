import os

import pytest
from typer.testing import CliRunner

from podcleaner_clips import banner
from podcleaner_clips.cli import app

TOP_LINE = banner.pixel_lines()[0]


@pytest.fixture
def terminal(monkeypatch):
    """A wide terminal that can print the half blocks."""
    monkeypatch.setattr(banner, "_stdout_is_tty", lambda: True)
    monkeypatch.setattr(banner, "_can_print", lambda chars: True)
    monkeypatch.setattr(banner.shutil, "get_terminal_size", lambda: os.terminal_size((100, 30)))
    monkeypatch.delenv(banner.NO_BANNER_ENV_VAR, raising=False)
    monkeypatch.setenv("NO_COLOR", "1")


def test_pixel_title_fits_in_80_columns():
    lines = banner.pixel_lines()
    assert len(lines) == 4
    assert len({len(line) for line in lines}) == 1
    assert len(lines[0]) <= 80
    assert set("".join(lines)) <= set("█▀▄ ")


def test_badge_has_a_margin_all_around():
    lines = banner.pixel_lines()
    assert lines[0][0] == lines[0][-1] == " "
    assert all(line[0] == " " and line[-1] == " " for line in lines)
    assert set(lines[-1]) == {" "}


def test_podcast_colours(terminal, monkeypatch):
    """Cream letters on a rust badge (Rich's colour system forced: Windows CI reports 16)."""
    real_console = banner.Console
    monkeypatch.setattr(
        banner,
        "Console",
        lambda **kw: real_console(**kw, force_terminal=True, color_system="truecolor"),
    )
    monkeypatch.delenv("NO_COLOR")
    output = CliRunner().invoke(app, []).output
    # Rich writes truecolor as r;g;b: cream on rust.
    assert "38;2;251;242;241" in output and "48;2;148;56;12" in output


def test_command_alone_shows_the_banner_then_the_help(terminal):
    result = CliRunner().invoke(app, [])
    assert result.exit_code == 0
    assert TOP_LINE.rstrip() in result.output
    assert "v1.0.0" in result.output
    assert result.output.index(TOP_LINE.rstrip()) < result.output.index("Usage")


def test_init_shows_the_banner(terminal, tmp_path):
    result = CliRunner().invoke(app, ["init", "--no-input", "--config", str(tmp_path / "c.toml")])
    assert result.exit_code == 0
    assert TOP_LINE.rstrip() in result.output


@pytest.mark.parametrize(
    "args", [["version"], ["--version"], ["config", "--path"], ["run", "--help"]]
)
def test_not_shown_for_other_commands(terminal, args):
    result = CliRunner().invoke(app, args)
    assert TOP_LINE.rstrip() not in result.output


def test_turned_off_by_option_or_variable(terminal, monkeypatch, tmp_path):
    result = CliRunner().invoke(app, ["--no-banner"])
    assert TOP_LINE.rstrip() not in result.output
    assert "Usage" in result.output
    monkeypatch.setenv(banner.NO_BANNER_ENV_VAR, "1")
    assert TOP_LINE.rstrip() not in CliRunner().invoke(app, []).output


def test_not_shown_when_output_is_not_a_terminal(terminal, monkeypatch):
    monkeypatch.setattr(banner, "_stdout_is_tty", lambda: False)
    assert TOP_LINE.rstrip() not in CliRunner().invoke(app, []).output


@pytest.mark.parametrize("narrow, can_print", [(True, True), (False, False)])
def test_plain_title_when_narrow_or_no_blocks(terminal, monkeypatch, narrow, can_print):
    if narrow:
        monkeypatch.setattr(banner.shutil, "get_terminal_size", lambda: os.terminal_size((40, 30)))
    monkeypatch.setattr(banner, "_can_print", lambda chars: can_print)
    result = CliRunner().invoke(app, [])
    assert TOP_LINE.rstrip() not in result.output
    assert "podcleaner-clips 1.0.0 - cut the clips noted while watching" in result.output


def test_can_print_checks_the_encoding(monkeypatch):
    class Ascii:
        encoding = "ascii"

    monkeypatch.setattr(banner.sys, "stdout", Ascii())
    assert not banner._can_print("█")
    assert banner._can_print("abc")
