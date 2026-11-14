from pathlib import Path

import pytest
from typer.testing import CliRunner

from podcleaner_clips.cli import app
from podcleaner_clips.config import (
    CONFIG_ENV_VAR,
    Settings,
    default_config_path,
    load_settings,
    write_template,
)
from podcleaner_clips.errors import ClipsError


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_applied(tmp_path):
    cfg = _write(tmp_path / "config.toml", f'episodes_dir = "{(tmp_path / "ep").as_posix()}"\n')
    s = load_settings(cfg)
    assert isinstance(s, Settings)
    assert s.episodes_dir == tmp_path / "ep"
    assert s.films_dir is None
    assert s.transition_sound is None
    assert s.preferred_dub == "VFF"
    assert s.tolerance_s == 15.0
    assert s.use_subtitles is True
    assert (s.score_found, s.score_sure) == (70, 85)
    assert s.sentence_gap_s == 0.6
    assert (s.pad_before_s, s.pad_after_s) == (0.10, 0.25)
    assert s.whisper_model == "large-v3-turbo"
    assert s.fade_s == 0.7
    assert (s.lufs, s.true_peak) == (-16.0, -1.0)
    assert s.claude_enabled is True
    assert s.claude_model == "claude-haiku-5-5"


def test_sections_override_defaults(tmp_path):
    cfg = _write(
        tmp_path / "config.toml",
        'episodes_dir = "ep"\n'
        'preferred_dub = "VFQ"\n'
        "[adjust]\ntolerance_s = 10\nuse_subtitles = false\n"
        "[audio]\nfade_s = 1.0\n"
        '[claude]\nenabled = false\nmodel = "autre"\n',
    )
    s = load_settings(cfg)
    assert s.preferred_dub == "VFQ"
    assert s.tolerance_s == 10.0
    assert s.use_subtitles is False
    assert s.fade_s == 1.0
    assert s.claude_enabled is False
    assert s.claude_model == "autre"


def test_relative_paths_resolve_against_config_dir(tmp_path):
    cfg = _write(tmp_path / "conf" / "config.toml", 'episodes_dir = "episodes"\n')
    assert load_settings(cfg).episodes_dir == tmp_path / "conf" / "episodes"


def test_default_path_is_in_user_config_dir():
    path = default_config_path()
    assert path.name == "config.toml"
    assert "podcleaner-clips" in str(path)


def test_env_var_overrides_default_path(tmp_path, monkeypatch):
    cfg = _write(tmp_path / "ailleurs.toml", 'episodes_dir = "ep"\n')
    monkeypatch.setenv(CONFIG_ENV_VAR, str(cfg))
    assert load_settings().episodes_dir == tmp_path / "ep"


def test_argument_beats_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv(CONFIG_ENV_VAR, str(tmp_path / "absent.toml"))
    cfg = _write(tmp_path / "config.toml", 'episodes_dir = "ep"\n')
    assert load_settings(cfg).episodes_dir == tmp_path / "ep"


def test_missing_file_message_mentions_config_init(tmp_path):
    missing = tmp_path / "nope" / "config.toml"
    with pytest.raises(ClipsError) as exc:
        load_settings(missing)
    assert str(missing) in str(exc.value)
    assert "podcleaner-clips config init" in str(exc.value)


def test_missing_episodes_dir_is_an_error(tmp_path):
    cfg = _write(tmp_path / "config.toml", 'preferred_dub = "VFF"\n')
    with pytest.raises(ClipsError, match="episodes_dir"):
        load_settings(cfg)


@pytest.mark.parametrize(
    "text, key",
    [
        ('episode_dir = "ep"\n', "episode_dir"),
        ('episodes_dir = "ep"\n[adjust]\ntolerence_s = 3\n', "tolerence_s"),
        ('episodes_dir = "ep"\n[sounds]\nfade_s = 1\n', "sounds"),
    ],
)
def test_unknown_key_is_an_error(tmp_path, text, key):
    cfg = _write(tmp_path / "config.toml", text)
    with pytest.raises(ClipsError, match=key):
        load_settings(cfg)


def test_wrong_type_is_an_error(tmp_path):
    cfg = _write(tmp_path / "config.toml", 'episodes_dir = "ep"\n[audio]\nfade_s = "long"\n')
    with pytest.raises(ClipsError, match="fade_s"):
        load_settings(cfg)


def test_invalid_toml_is_an_error(tmp_path):
    cfg = _write(tmp_path / "config.toml", "episodes_dir = \n")
    with pytest.raises(ClipsError, match="config.toml"):
        load_settings(cfg)


def test_preferred_dub_must_be_vff_or_vfq(tmp_path):
    cfg = _write(tmp_path / "config.toml", 'episodes_dir = "ep"\npreferred_dub = "VO"\n')
    with pytest.raises(ClipsError, match="VFF"):
        load_settings(cfg)
    ok = _write(tmp_path / "ok.toml", 'episodes_dir = "ep"\npreferred_dub = "vfq"\n')
    assert load_settings(ok).preferred_dub == "VFQ"


def test_paths_with_accents_and_tilde(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    cfg = _write(
        tmp_path / "Réglages été" / "config.toml",
        'episodes_dir = "~/Épisodes"\ntransition_sound = "~/Sons/transition à.wav"\n',
    )
    s = load_settings(cfg)
    assert s.episodes_dir == tmp_path / "Épisodes"
    assert s.transition_sound == tmp_path / "Sons" / "transition à.wav"


def test_template_roundtrips(tmp_path):
    cfg = tmp_path / "sub" / "config.toml"
    write_template(cfg)
    text = cfg.read_text(encoding="utf-8")
    assert "episodes_dir" in text
    with pytest.raises(ClipsError, match="episodes_dir"):
        load_settings(cfg)  # the template leaves episodes_dir to fill in
    cfg.write_text(text.replace('# episodes_dir = ""', 'episodes_dir = "ep"'), encoding="utf-8")
    s = load_settings(cfg)
    assert s.episodes_dir == cfg.parent / "ep"
    assert s.tolerance_s == 15.0


def test_write_template_refuses_to_overwrite(tmp_path):
    cfg = _write(tmp_path / "config.toml", "mien\n")
    with pytest.raises(ClipsError, match="already exists"):
        write_template(cfg)
    assert cfg.read_text(encoding="utf-8") == "mien\n"


def test_cli_config_init_and_show(tmp_path):
    cfg = tmp_path / "config.toml"
    runner = CliRunner()
    result = runner.invoke(app, ["config", "init", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert cfg.exists()
    assert str(cfg) in result.output
    cfg.write_text(
        cfg.read_text(encoding="utf-8").replace('# episodes_dir = ""', 'episodes_dir = "ep"'),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["config", "show", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "episodes_dir" in result.output
    assert str(tmp_path / "ep") in result.output
    assert "large-v3-turbo" in result.output


def test_english_keys_give_no_notice(tmp_path):
    cfg = _write(tmp_path / "config.toml", 'episodes_dir = "ep"\n[audio]\nfade_s = 1.0\n')
    assert load_settings(cfg).notices == ()


def test_old_french_keys_still_read_with_notice(tmp_path):
    cfg = _write(
        tmp_path / "config.toml",
        'dossier_episodes = "ep"\n'
        'son_transition = "t.wav"\n'
        'doublage_prefere = "VFQ"\n'
        "[ajustement]\nsous_titres = false\n"
        "[son]\nfondu_s = 1.0\n"
        '[claude]\nactif = false\nmodele = "autre"\n',
    )
    s = load_settings(cfg)
    assert s.episodes_dir == tmp_path / "ep"
    assert s.transition_sound == tmp_path / "t.wav"
    assert s.preferred_dub == "VFQ"
    assert s.use_subtitles is False
    assert s.fade_s == 1.0
    assert (s.claude_enabled, s.claude_model) == (False, "autre")
    assert len(s.notices) == 1
    assert "dossier_episodes → episodes_dir" in s.notices[0]
    assert "[son] fondu_s → [audio] fade_s" in s.notices[0]


def test_old_section_with_new_key_is_read_with_notice(tmp_path):
    cfg = _write(
        tmp_path / "config.toml", 'episodes_dir = "ep"\n[ajustement]\nuse_subtitles = false\n'
    )
    s = load_settings(cfg)
    assert s.use_subtitles is False
    assert "[ajustement] → [adjust]" in s.notices[0]


def test_old_and_new_name_together_is_an_error(tmp_path):
    cfg = _write(tmp_path / "config.toml", 'episodes_dir = "ep"\ndossier_episodes = "ep2"\n')
    with pytest.raises(ClipsError, match="twice"):
        load_settings(cfg)


def test_config_show_prints_the_notice(tmp_path):
    cfg = _write(tmp_path / "config.toml", 'dossier_episodes = "ep"\n')
    result = CliRunner().invoke(app, ["config", "show", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "episodes_dir = " in result.output
    assert "dossier_episodes → episodes_dir" in result.output


@pytest.mark.parametrize(
    "claude, backend",
    [
        ("", "auto"),
        ('[claude]\nbackend = "CLI"\n', "cli"),
        ('[claude]\nbackend = "api"\n', "api"),
        ("[claude]\nenabled = false\n", "off"),
        ('[claude]\nbackend = "cli"\nenabled = false\n', "off"),
    ],
)
def test_claude_backend(tmp_path, claude, backend):
    cfg = _write(tmp_path / "config.toml", 'episodes_dir = "ep"\n' + claude)
    assert load_settings(cfg).claude_backend == backend


def test_unknown_claude_backend_is_an_error(tmp_path):
    cfg = _write(tmp_path / "config.toml", 'episodes_dir = "ep"\n[claude]\nbackend = "web"\n')
    with pytest.raises(ClipsError, match="backend"):
        load_settings(cfg)
