import json
from pathlib import Path

import pytest
from make_test_film import make_test_film
from typer.testing import CliRunner

from podcleaner_clips import pipeline
from podcleaner_clips.adjust import Word
from podcleaner_clips.cli import app
from podcleaner_clips.errors import ClipsError
from podcleaner_clips.index import _LEGACY_KEYS as _INDEX_LEGACY_KEYS
from podcleaner_clips.index import INDEX_NAME, LEGACY_INDEX_NAME
from podcleaner_clips.pipeline import RunOptions, run
from podcleaner_clips.render_video import VIDEO_RENDER_VERSION

# Two clips of the 12 s test film.
NOTES = "file: {film}\n\n0:02 bonjour tout le monde 0:05\n0:07 au revoir 0:09\n"


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
            f'episodes_dir = "{self.episodes.as_posix()}"\n'
            f'transition_sound = "{transition.as_posix()}"\n'
            '[claude]\nbackend = "off"\n',
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
    "clips.json",
    "video/TF-01-bonjour-tout-le-monde.mp4",
    "video/TF-02-au-revoir.mp4",
]


def test_end_to_end_no_adjust(setup):
    report = setup.run(adjust=False)

    assert report.failures == 0
    assert setup.files() == EXPECTED
    assert "abbreviation: TF" in setup.notes.read_text(encoding="utf-8")
    first = setup.index()["clips"][0]
    assert first["chosen"]["method"] == "notes"
    assert first["chosen"]["start"] == "00:00:02.000"
    assert setup.index()["film"]["abbreviation"] == "TF"
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
        "clips.json",
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
        "clips.json",
        "video/TF-01-premier-mot.mp4",
        "video/TF-02-bonjour-tout-le-monde.mp4",
        "video/TF-03-au-revoir.mp4",
    ]
    assert [c["number"] for c in setup.index()["clips"]] == [1, 2, 3]


def test_removed_line_files_are_kept_and_listed(setup):
    setup.run(adjust=False)
    text = setup.notes.read_text(encoding="utf-8")
    setup.notes.write_text(text.replace("0:07 au revoir 0:09\n", ""), encoding="utf-8")
    setup.lines.clear()

    setup.run(adjust=False)

    assert "audio/TF-02-au-revoir.wav" in setup.files()
    assert any("TF-02-au-revoir.wav" in line for line in setup.lines)
    assert [c["number"] for c in setup.index()["clips"]] == [1]


def test_clip_past_film_end_fails_alone(tmp_path, test_film, transition_wav):
    notes = "file: {film}\n0:02 bonjour tout le monde 0:05\n0:10 trop loin 0:20\n"
    s = Setup(tmp_path, test_film, transition_wav, notes)

    report = s.run(adjust=False)

    assert report.failures == 1
    assert "audio/TF-01-bonjour-tout-le-monde.wav" in s.files()
    assert not any("trop-loin" in f for f in s.files())
    assert any(line.startswith("02 ") and "after the end of the film" in line for line in s.lines)


def test_film_resolved_from_films_dir(tmp_path, test_film, transition_wav):
    s = Setup(tmp_path, test_film, transition_wav, "file: test film.mkv\n0:02 a b 0:05\n")
    s.config.write_text(
        f'episodes_dir = "{s.episodes.as_posix()}"\n'
        f'transition_sound = "{transition_wav.as_posix()}"\n'
        f'films_dir = "{test_film.parent.as_posix()}"\n'
        '[claude]\nbackend = "off"\n',
        encoding="utf-8",
    )

    report = s.run(adjust=False, dry_run=True)

    assert report.failures == 0


def test_missing_film_lists_the_places_searched(tmp_path, test_film, transition_wav):
    s = Setup(tmp_path, test_film, transition_wav, "file: absent.mkv\n0:02 a b 0:05\n")
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
        f'episodes_dir = "{setup.episodes.as_posix()}"\n[claude]\nbackend = "off"\n',
        encoding="utf-8",
    )
    with pytest.raises(ClipsError, match="transition_sound"):
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

    first = setup.index()["clips"][0]
    assert first["chosen"]["method"] == "whisper"
    assert first["chosen"]["start"] != first["noted"]["start"]
    assert first["found_fragments"] == ["bonjour tout le monde"]


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


def _to_legacy(value, key=None):
    """A version 2 index written back with the French keys of version 1."""
    french = {v: k for k, v in _INDEX_LEGACY_KEYS.items()}
    if isinstance(value, list):
        return [_to_legacy(v) for v in value]
    if not isinstance(value, dict) or key == "files":
        return value
    out = {french.get(k, k): _to_legacy(v, k) for k, v in value.items()}
    if out.get("type") in ("abbreviation", "bounds"):
        out["type"] = {"abbreviation": "abreviation", "bounds": "bornes"}[out["type"]]
    return out


def test_legacy_index_and_french_header_are_migrated_without_rerender(setup):
    setup.run(adjust=False)
    data = setup.index()
    data["version"] = 1
    (setup.out / LEGACY_INDEX_NAME).write_text(json.dumps(_to_legacy(data)), encoding="utf-8")
    (setup.out / INDEX_NAME).unlink()
    setup.notes.write_text(
        setup.notes.read_text(encoding="utf-8").replace("file:", "fichier:"), encoding="utf-8"
    )
    setup.lines.clear()

    setup.run(adjust=False)

    assert setup.files() == EXPECTED  # clips.json back, extraits.json gone
    assert sum("unchanged" in line for line in setup.lines) == 2
    assert any("fichier: → file:" in line for line in setup.lines)


def _drop_video_version(setup) -> None:
    """Makes the index look written before the video fades (no "video_version")."""
    data = setup.index()
    for clip in data["clips"]:
        clip.pop("video_version")
    (setup.out / INDEX_NAME).write_text(json.dumps(data), encoding="utf-8")


def test_videos_from_before_the_fades_are_redone_alone(setup):
    setup.run(adjust=False)
    _drop_video_version(setup)
    wav = setup.out / "audio" / "TF-01-bonjour-tout-le-monde.wav"
    mp4 = setup.out / "video" / "TF-01-bonjour-tout-le-monde.mp4"
    wav_before, mp4_before = wav.stat().st_mtime_ns, mp4.stat().st_ino
    setup.lines.clear()

    setup.run(adjust=False)

    assert setup.files() == EXPECTED
    assert wav.stat().st_mtime_ns == wav_before  # the sound is not touched
    assert mp4.stat().st_ino != mp4_before  # written again (renamed into place)
    assert sum("video redone" in line for line in setup.lines) == 2
    assert all(c["video_version"] == VIDEO_RENDER_VERSION for c in setup.index()["clips"])

    setup.lines.clear()
    setup.run(adjust=False)  # nothing left to do
    assert sum("unchanged" in line for line in setup.lines) == 2


def test_audio_only_run_keeps_an_old_video_as_it_is(setup):
    setup.run(adjust=False)
    _drop_video_version(setup)
    mp4 = setup.out / "video" / "TF-01-bonjour-tout-le-monde.mp4"
    before = mp4.stat().st_ino

    setup.run(adjust=False, video=False)

    assert mp4.stat().st_ino == before
    assert all(c["video_version"] == 1 for c in setup.index()["clips"])  # still to redo


def _with_transition_video(setup, video) -> None:
    text = setup.config.read_text(encoding="utf-8")
    line = f"transition_video = '{Path(video).as_posix()}'\n"
    lines = [x for x in text.splitlines(keepends=True) if not x.startswith("transition_video")]
    setup.config.write_text(line + "".join(lines), encoding="utf-8")


def test_changing_the_transition_video_redoes_the_videos_only(
    setup, transition_mp4, other_transition_mp4
):
    _with_transition_video(setup, transition_mp4)
    setup.run(adjust=False)
    first = setup.index()["clips"][0]
    assert first["transition_video_sha"] is not None
    wav = setup.out / "audio" / "TF-01-bonjour-tout-le-monde.wav"
    mp4 = setup.out / "video" / "TF-01-bonjour-tout-le-monde.mp4"
    wav_before, mp4_before = wav.stat().st_mtime_ns, mp4.stat().st_ino

    _with_transition_video(setup, other_transition_mp4)
    setup.lines.clear()
    setup.run(adjust=False)

    assert wav.stat().st_mtime_ns == wav_before
    assert mp4.stat().st_ino != mp4_before
    assert sum("video redone" in line for line in setup.lines) == 2
    assert setup.index()["clips"][0]["transition_video_sha"] != first["transition_video_sha"]


def test_missing_or_pictureless_transition_video_is_an_error(setup, transition_wav):
    _with_transition_video(setup, setup.root / "absent.mp4")
    with pytest.raises(ClipsError, match="Transition video not found"):
        setup.run(adjust=False)
    _with_transition_video(setup, transition_wav)
    with pytest.raises(ClipsError, match="has no picture"):
        setup.run(adjust=False)


def test_transition_video_ignored_without_transition_or_video(setup):
    _with_transition_video(setup, setup.root / "absent.mp4")  # never opened
    setup.run(adjust=False, transition=False)
    setup.run(adjust=False, video=False)
