from pathlib import Path

import pytest
from typer.testing import CliRunner

from podcleaner_clips.cli import app
from podcleaner_clips.config import load_settings
from podcleaner_clips.wizard import clean_path


@pytest.fixture
def tty(monkeypatch):
    monkeypatch.setattr("podcleaner_clips.cli._stdin_is_tty", lambda: True)


def init(cfg: Path, answers: list[str]):
    return CliRunner().invoke(app, ["init", "--config", str(cfg)], input="\n".join(answers) + "\n")


def test_new_config_from_answers(tmp_path, tty, transition_wav):
    cfg = tmp_path / "conf" / "config.toml"
    episodes = tmp_path / "Mes épisodes"
    result = init(
        cfg,
        [
            str(episodes),  # does not exist yet
            "y",  # create it
            "",  # no films folder
            str(transition_wav),
            "",  # no transition video
            "vfq",
            "n",  # no Claude
        ],
    )

    assert result.exit_code == 0, result.output
    assert episodes.is_dir()
    s = load_settings(cfg)
    assert s.episodes_dir == episodes
    assert s.films_dir is None
    assert s.transition_sound == transition_wav
    assert s.preferred_dub == "VFQ"
    assert s.claude_backend == "off"
    assert s.notices == ()
    assert "Configuration saved" in result.output
    assert "run <notes file" in result.output
    text = cfg.read_text(encoding="utf-8")
    assert "# tolerance_s = 15.0" in text  # the other settings stay, commented


def test_existing_values_are_the_defaults_and_other_settings_kept(tmp_path, tty, transition_wav):
    films = tmp_path / "films"
    films.mkdir()
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f"dossier_episodes = '{tmp_path.as_posix()}'\n"  # old French name
        f"dossier_films = '{films.as_posix()}'\n"
        f"son_transition = '{transition_wav.as_posix()}'\n"
        "[ajustement]\ntolerance_s = 10\n"
        '[claude]\nbackend = "cli"\nmodel = "m"\n',
        encoding="utf-8",
    )

    result = init(cfg, ["", "", "", "", "", "", "", "y"])  # Enter everywhere, then replace

    assert result.exit_code == 0, result.output
    s = load_settings(cfg)
    assert (s.episodes_dir, s.films_dir, s.transition_sound) == (tmp_path, films, transition_wav)
    assert s.tolerance_s == 10.0
    assert (s.claude_backend, s.claude_model) == ("cli", "m")
    assert s.notices == ()  # rewritten with the English names
    assert "dossier_episodes" not in cfg.read_text(encoding="utf-8")


def test_replace_declined_writes_nothing(tmp_path, tty):
    cfg = tmp_path / "config.toml"
    cfg.write_text(f"episodes_dir = '{tmp_path.as_posix()}'\n", encoding="utf-8")
    before = cfg.read_bytes()

    result = init(cfg, ["", "", "", "", "n", "n"])

    assert result.exit_code == 1
    assert "Nothing was written" in result.output
    assert cfg.read_bytes() == before


def test_dash_removes_an_optional_path(tmp_path, tty):
    films = tmp_path / "films"
    films.mkdir()
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f"episodes_dir = '{tmp_path.as_posix()}'\nfilms_dir = '{films.as_posix()}'\n",
        encoding="utf-8",
    )
    result = init(cfg, ["", "-", "", "", "n", "y"])
    assert result.exit_code == 0, result.output
    assert load_settings(cfg).films_dir is None


def test_wrong_answers_are_asked_again(tmp_path, tty, transition_wav):
    cfg = tmp_path / "config.toml"
    not_sound = tmp_path / "notes.txt"
    not_sound.write_text("hello", encoding="utf-8")
    result = init(
        cfg,
        [
            str(not_sound),  # a file, not a folder
            str(tmp_path),
            str(tmp_path / "absent"),  # no such films folder
            "",
            str(tmp_path / "absent.wav"),  # no such sound
            str(not_sound),  # not a sound
            str(transition_wav),
            str(transition_wav),  # a sound, not a video
            "",
            "VO",  # not a choice
            "VFF",
            "n",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "is a file, not a folder" in result.output
    assert "No folder at" in result.output
    assert "No file at" in result.output
    assert "ffmpeg could not read" in result.output or "has no sound" in result.output
    assert "has no picture" in result.output
    assert load_settings(cfg).transition_sound == transition_wav


def test_claude_yes_keeps_auto_and_asks_the_model(tmp_path, tty, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = tmp_path / "config.toml"
    result = init(cfg, [str(tmp_path), "", "", "", "y", "claude-sonnet-5-5"])
    assert result.exit_code == 0, result.output
    assert "Neither Claude Code nor an API key" in result.output
    s = load_settings(cfg)
    assert (s.claude_backend, s.claude_model) == ("auto", "claude-sonnet-5-5")


def test_claude_status_with_logged_in_cli(tmp_path, tty, monkeypatch):
    monkeypatch.setattr("podcleaner_clips.claude.find_cli", lambda: "/bin/claude")
    monkeypatch.setattr("podcleaner_clips.claude.cli_logged_in", lambda cli: True)
    result = init(tmp_path / "config.toml", [str(tmp_path), "", "", "", "n"])
    assert "can use your subscription" in result.output


def test_interrupted_init_leaves_no_file(tmp_path, tty):
    cfg = tmp_path / "config.toml"
    result = init(cfg, [str(tmp_path)])  # input ends, like Ctrl+C
    assert result.exit_code != 0
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("args", [["--no-input"], []])
def test_without_a_terminal_writes_the_template(tmp_path, args):
    cfg = tmp_path / "config.toml"
    result = CliRunner().invoke(app, ["init", "--config", str(cfg), *args])  # stdin not a tty
    assert result.exit_code == 0, result.output
    assert "# episodes_dir = " in cfg.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "text, windows, expected",
    [
        (
            "  /Users/me/Mes\\ films/Le\\ Dîner\\ \\(1998\\).mkv ",
            False,
            "/Users/me/Mes films/Le Dîner (1998).mkv",
        ),
        ("'/Users/me/l'\\''intro.wav'", False, "/Users/me/l'\\''intro.wav"),
        ('"C:\\Podcast\\Épisodes"', True, "C:\\Podcast\\Épisodes"),
        ("C:\\Podcast\\Episodes", True, "C:\\Podcast\\Episodes"),
        ("'/Volumes/Films 2/x.mkv'", False, "/Volumes/Films 2/x.mkv"),
        ("~/Podcast", False, "~/Podcast"),
    ],
)
def test_clean_path(text, windows, expected):
    assert clean_path(text, windows=windows) == expected


def test_transition_video_is_asked_after_the_sound(tmp_path, tty, transition_wav, test_film):
    cfg = tmp_path / "config.toml"
    result = init(cfg, [str(tmp_path), "", str(transition_wav), str(test_film), "", "n"])
    assert result.exit_code == 0, result.output
    assert load_settings(cfg).transition_video == test_film


def test_no_transition_video_question_without_a_sound(tmp_path, tty):
    cfg = tmp_path / "config.toml"
    result = init(cfg, [str(tmp_path), "", "", "", "n"])
    assert result.exit_code == 0, result.output
    assert "Video shown during the transition" not in result.output
    assert load_settings(cfg).transition_video is None
