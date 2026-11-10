import json
from pathlib import Path

import pytest
from make_test_film import make_test_film
from typer.testing import CliRunner

from podcleaner_clips import pipeline
from podcleaner_clips.adjust import Word
from podcleaner_clips.cli import app
from podcleaner_clips.errors import ClipsError
from podcleaner_clips.index import INDEX_NAME
from podcleaner_clips.pipeline import RunOptions, run

# Two clips of the 12 s test film.
NOTES = "fichier: {film}\n\n0:02 bonjour tout le monde 0:05\n0:07 au revoir 0:09\n"


class FakeTranscriber:
    """A fixed script; the first clip's line is said from 2.4 s to 4.0 s."""

    SCRIPT = (
        [Word("mot", t, t + 0.4) for t in (0.0, 0.5, 1.0)]
        + [Word("mot.", 1.5, 1.9)]
        + [
            Word(w, t, t + 0.4)
            for w, t in zip(["Bonjour", "tout", "le", "monde."], [2.4, 2.8, 3.2, 3.6], strict=True)
        ]
        + [Word("suite.", t / 2, t / 2 + 0.4) for t in range(9, 24)]
    )

    def __init__(self) -> None:
        self.calls = 0

    def words(self, audio, offset: float) -> list[Word]:
        self.calls += 1
        end = offset + len(audio) / 16000
        return [w for w in self.SCRIPT if offset <= w.start and w.end <= end]


class Setup:
    def __init__(self, tmp_path: Path, film: Path, transition: Path, notes: str = NOTES) -> None:
        self.root = tmp_path
        self.episodes = tmp_path / "episodes"
        self.config = tmp_path / "config.toml"
        self.config.write_text(
            f'dossier_episodes = "{self.episodes.as_posix()}"\n'
            f'son_transition = "{transition.as_posix()}"\n'
            "[claude]\nactif = false\n",
            encoding="utf-8",
        )
        self.notes = tmp_path / "notes" / "film.md"
        self.notes.parent.mkdir()
        self.notes.write_text(notes.format(film=film.as_posix()), encoding="utf-8")
        self.lines: list[str] = []

    def run(self, **kw):
        kw.setdefault("transcriber", FakeTranscriber())
        transcriber = kw.pop("transcriber")
        opts = RunOptions(notes=self.notes, config=self.config, **kw)
        return run(opts, transcriber=transcriber, echo=self.lines.append)

    @property
    def out(self) -> Path:
        return self.episodes / "test film"

    def files(self) -> list[str]:
        return sorted(
            p.relative_to(self.out).as_posix() for p in self.out.rglob("*") if p.is_file()
        )

    def index(self) -> dict:
        return json.loads((self.out / INDEX_NAME).read_text(encoding="utf-8"))


@pytest.fixture
def setup(tmp_path, test_film, transition_wav) -> Setup:
    return Setup(tmp_path, test_film, transition_wav)


EXPECTED = [
    "audio/TF-01-bonjour-tout-le-monde.wav",
    "audio/TF-02-au-revoir.wav",
    "extraits.json",
    "video/TF-01-bonjour-tout-le-monde.mp4",
    "video/TF-02-au-revoir.mp4",
]


def test_end_to_end_no_adjust(setup):
    report = setup.run(adjust=False)

    assert report.failures == 0
    assert setup.files() == EXPECTED
    assert "abreviation: TF" in setup.notes.read_text(encoding="utf-8")
    first = setup.index()["extraits"][0]
    assert first["retenu"]["methode"] == "notes"
    assert first["retenu"]["debut"] == "00:00:02.000"
    assert setup.index()["film"]["abreviation"] == "TF"
    assert any("TF-01-bonjour-tout-le-monde" in line and "new" in line for line in setup.lines)


def test_dry_run_writes_nothing(setup):
    before = setup.notes.read_bytes()

    report = setup.run(adjust=False, dry_run=True)

    assert report.index is None
    assert not setup.episodes.exists()
    assert setup.notes.read_bytes() == before
    assert any("TF-02-au-revoir" in line for line in setup.lines)


def test_audio_only_and_video_only(setup):
    setup.run(adjust=False, video=False)
    assert setup.files() == [
        "audio/TF-01-bonjour-tout-le-monde.wav",
        "audio/TF-02-au-revoir.wav",
        "extraits.json",
    ]

    setup.run(adjust=False, audio=False)  # the WAV used for the video is temporary
    assert setup.files() == EXPECTED
    assert not list(setup.root.rglob("*.part.*"))


def test_audio_and_video_only_together_is_error(setup):
    with pytest.raises(ClipsError, match="audio-only"):
        setup.run(adjust=False, audio=False, video=False)


def test_second_run_is_all_unchanged(setup, monkeypatch):
    setup.run()
    renders = []
    monkeypatch.setattr(pipeline, "render_audio", lambda *a, **k: renders.append(a))
    monkeypatch.setattr(pipeline, "render_video", lambda *a, **k: renders.append(a))
    transcriber = FakeTranscriber()
    setup.lines.clear()

    report = setup.run(transcriber=transcriber)

    assert report.failures == 0
    assert renders == [] and transcriber.calls == 0
    clip_lines = [line for line in setup.lines if line.startswith(("01 ", "02 "))]
    assert len(clip_lines) == 2 and all("unchanged" in line for line in clip_lines)


def test_inserted_line_renames_files(setup):
    setup.run(adjust=False)
    text = setup.notes.read_text(encoding="utf-8")
    setup.notes.write_text(
        text.replace("0:02 bonjour", "0:00 premier mot 0:01\n0:02 bonjour"), encoding="utf-8"
    )

    setup.run(adjust=False)

    assert setup.files() == [
        "audio/TF-01-premier-mot.wav",
        "audio/TF-02-bonjour-tout-le-monde.wav",
        "audio/TF-03-au-revoir.wav",
        "extraits.json",
        "video/TF-01-premier-mot.mp4",
        "video/TF-02-bonjour-tout-le-monde.mp4",
        "video/TF-03-au-revoir.mp4",
    ]
    assert [c["numero"] for c in setup.index()["extraits"]] == [1, 2, 3]


def test_removed_line_files_are_kept_and_listed(setup):
    setup.run(adjust=False)
    text = setup.notes.read_text(encoding="utf-8")
    setup.notes.write_text(text.replace("0:07 au revoir 0:09\n", ""), encoding="utf-8")
    setup.lines.clear()

    setup.run(adjust=False)

    assert "audio/TF-02-au-revoir.wav" in setup.files()
    assert any("TF-02-au-revoir.wav" in line for line in setup.lines)
    assert [c["numero"] for c in setup.index()["extraits"]] == [1]


def test_clip_past_film_end_fails_alone(tmp_path, test_film, transition_wav):
    notes = "fichier: {film}\n0:02 bonjour tout le monde 0:05\n0:10 trop loin 0:20\n"
    s = Setup(tmp_path, test_film, transition_wav, notes)

    report = s.run(adjust=False)

    assert report.failures == 1
    assert "audio/TF-01-bonjour-tout-le-monde.wav" in s.files()
    assert not any("trop-loin" in f for f in s.files())
    assert any(line.startswith("02 ") and "after the end of the film" in line for line in s.lines)


def test_film_resolved_from_films_dir(tmp_path, test_film, transition_wav):
    s = Setup(tmp_path, test_film, transition_wav, "fichier: test film.mkv\n0:02 a b 0:05\n")
    s.config.write_text(
        f'dossier_episodes = "{s.episodes.as_posix()}"\n'
        f'son_transition = "{transition_wav.as_posix()}"\n'
        f'dossier_films = "{test_film.parent.as_posix()}"\n'
        "[claude]\nactif = false\n",
        encoding="utf-8",
    )

    report = s.run(adjust=False, dry_run=True)

    assert report.failures == 0


def test_missing_film_lists_the_places_searched(tmp_path, test_film, transition_wav):
    s = Setup(tmp_path, test_film, transition_wav, "fichier: absent.mkv\n0:02 a b 0:05\n")
    with pytest.raises(ClipsError, match="--film") as err:
        s.run(adjust=False, dry_run=True)
    assert str(s.notes.parent / "absent.mkv") in str(err.value)


def test_film_option_and_title_from_film_name(tmp_path, transition_wav):
    film = make_test_film(tmp_path / "films" / "Xavier (2015) Bluray.mkv", duration=8.0)
    s = Setup(tmp_path, film, transition_wav, "0:02 a b 0:05\n")

    s.run(film=film, adjust=False, video=False)

    assert (s.episodes / "Xavier (2015)" / "audio" / "XA-01-a-b.wav").is_file()


def test_missing_transition_sound_is_an_error(setup):
    setup.config.write_text(
        f'dossier_episodes = "{setup.episodes.as_posix()}"\n[claude]\nactif = false\n',
        encoding="utf-8",
    )
    with pytest.raises(ClipsError, match="son_transition"):
        setup.run(adjust=False)
    setup.run(adjust=False, transition=False, dry_run=True)  # fine without a transition


def test_subtitles_used_when_present(tmp_path, transition_wav, monkeypatch):
    srt = "1\n00:00:02,400 --> 00:00:04,200\nBonjour tout le monde.\n"
    film = make_test_film(tmp_path / "films" / "test film.mkv", subtitles=srt)
    s = Setup(tmp_path, film, transition_wav)
    seen = []
    real = pipeline.adjust_cut
    monkeypatch.setattr(
        pipeline,
        "adjust_cut",
        lambda w, f, anchors, *a: seen.append(anchors) or real(w, f, anchors, *a),
    )

    s.run(dry_run=True)

    assert seen[0] and seen[0][0].start == pytest.approx(2.4, abs=0.1)


def test_fake_transcriber_cut_written_to_index(setup):
    setup.run(video=False)

    first = setup.index()["extraits"][0]
    assert first["retenu"]["methode"] == "whisper"
    assert first["retenu"]["debut"] != first["notes"]["debut"]
    assert first["fragments_trouves"] == ["bonjour tout le monde"]


def test_cli_run_exit_codes(setup):
    runner = CliRunner()
    ok = runner.invoke(
        app, ["run", str(setup.notes), "--config", str(setup.config), "--no-adjust", "--dry-run"]
    )
    assert ok.exit_code == 0, ok.output
    both = runner.invoke(
        app,
        ["run", str(setup.notes), "--config", str(setup.config), "--audio-only", "--video-only"],
    )
    assert both.exit_code != 0
