import pytest
from make_test_film import make_test_film

from podcleaner_clips import media
from podcleaner_clips.errors import ClipsError
from podcleaner_clips.media import (
    AudioTrack,
    SubtitleTrack,
    choose_audio_track,
    choose_subtitle_track,
    decode_window,
    extract_subtitles,
    probe,
    require_ffmpeg,
)
from podcleaner_clips.naming import parse_tc


def audio(*specs):
    return [
        AudioTrack(index=i, language=lang, title=title, channels=ch)
        for i, (lang, title, ch) in enumerate(specs)
    ]


def subs(*specs):
    return [
        SubtitleTrack(index=i, language=lang, title=title, codec=codec)
        for i, (lang, title, codec) in enumerate(specs)
    ]


# --- choose_audio_track ---


def test_prefers_vff_when_vff_and_vfq_exist():
    tracks = audio(("fre", "Français VFF", 6), ("eng", "English", 6), ("fre", "Français VFQ", 6))
    assert choose_audio_track(tracks, None)[0].index == 0
    assert choose_audio_track(tracks, None, preferred_dub="VFQ")[0].index == 2
    assert choose_audio_track(tracks, None)[1] is None


def test_detects_vfq_from_language_tag():
    tracks = audio(("fre", "Français", 2), ("fr-CA", "", 2))
    assert choose_audio_track(tracks, None, preferred_dub="VFQ")[0].index == 1


@pytest.mark.parametrize("title", ["Québec", "Quebec", "Canadien", "VFQ 5.1"])
def test_detects_vfq_from_title(title):
    tracks = audio(("fre", "Français", 2), ("fre", title, 2))
    assert choose_audio_track(tracks, None, preferred_dub="VFQ")[0].index == 1


def test_vff_from_title_france_or_bare_vf():
    tracks = audio(("fre", "VFQ", 2), ("fre", "VF", 2))
    assert choose_audio_track(tracks, None)[0].index == 1
    tracks = audio(("fre", "VFQ", 2), ("fre", "France", 2))
    assert choose_audio_track(tracks, None)[0].index == 1


def test_first_french_when_preferred_dub_missing():
    tracks = audio(("eng", "English", 2), ("fre", "Français", 2), ("fre", "VFQ", 2))
    assert choose_audio_track(tracks, None)[0].index == 1


def test_prefers_french_by_title_when_untagged():
    tracks = audio((None, "English", 2), (None, "VFF 5.1", 6))
    assert choose_audio_track(tracks, None)[0].index == 1


def test_falls_back_to_first_with_warning():
    tracks = audio((None, None, 2), ("eng", "Commentary", 6))
    track, warning = choose_audio_track(tracks, None)
    assert track.index == 0
    assert warning is not None
    assert "--audio-track" in warning
    assert "Commentary" in warning and "6 channels" in warning


def test_forced_track_is_used():
    tracks = audio(("fre", "VFF", 2), ("eng", "English", 2))
    assert choose_audio_track(tracks, 1) == (tracks[1], None)


def test_forced_out_of_range_lists_tracks():
    tracks = audio(("fre", "VFF", 2), ("eng", "English", 6))
    with pytest.raises(ClipsError) as exc:
        choose_audio_track(tracks, 5)
    assert "English" in str(exc.value) and "VFF" in str(exc.value)


def test_no_audio_track_is_an_error():
    with pytest.raises(ClipsError):
        choose_audio_track([], None)


# --- choose_subtitle_track ---


def test_chooses_full_french_text_subtitles():
    tracks = subs(
        ("fre", "Forcés", "subrip"),
        ("fre", "Complets", "subrip"),
        ("eng", "Full", "subrip"),
        ("fre", "", "hdmv_pgs_subtitle"),
    )
    assert choose_subtitle_track(tracks).title == "Complets"


def test_first_french_text_subtitles_without_full_title():
    tracks = subs(("eng", None, "subrip"), ("fre", None, "ass"), ("fre", "SDH", "subrip"))
    assert choose_subtitle_track(tracks).index == 2
    tracks = subs(("eng", None, "subrip"), ("fre", None, "ass"))
    assert choose_subtitle_track(tracks).index == 1


def test_forced_subtitles_are_skipped():
    tracks = subs(("fre", "Forced", "subrip"), ("fre", "FORCÉ", "subrip"))
    assert choose_subtitle_track(tracks) is None


def test_no_usable_subtitles():
    tracks = subs(("fre", "Complets", "hdmv_pgs_subtitle"), ("eng", "Full", "subrip"))
    assert choose_subtitle_track(tracks) is None
    assert choose_subtitle_track([]) is None


# --- ffmpeg ---


def test_probe_test_film(test_film):
    info = probe(test_film)
    assert abs(info.duration - 12.0) < 0.1
    assert [t.language for t in info.audio] == ["fre", "eng", "fre"]
    assert [t.index for t in info.audio] == [0, 1, 2]
    assert info.audio[0].title == "Français VFF"
    assert info.audio[0].channels == 2
    assert info.subtitles == []
    assert info.video is not None and info.video.width == 320  # cover art is not the video
    assert info.video.height == 240
    assert info.video.fps == "24/1"
    assert info.video.sar == "1:1"


def test_probe_six_channel_vf(tmp_path):
    film = make_test_film(tmp_path / "f.mkv", duration=2.0, vf_channels=6)
    assert [t.channels for t in probe(film).audio] == [6, 2, 2]


SRT = """\
1
00:00:01,000 --> 00:00:03,000
Ce bébé, c'est une connerie.

2
00:00:04,000 --> 00:00:06,000
Ça va te remettre les idées en place.
"""


def test_extract_subtitles_roundtrip(tmp_path):
    film = make_test_film(tmp_path / "f.mkv", duration=8.0, subtitles=SRT)
    info = probe(film)
    track = choose_subtitle_track(info.subtitles)
    assert track is not None and track.language == "fre"
    text = extract_subtitles(film, track)
    assert "Ce bébé, c'est une connerie." in text
    # Times are on the film clock that starts at 0 (the AAC priming offset of a few
    # ms is removed), the same clock decode_window seeks on.
    starts = [line.split(" --> ")[0] for line in text.splitlines() if " --> " in line]
    seconds = [parse_tc(s.replace(",", ".")) for s in starts]
    assert seconds == pytest.approx([1.0, 4.0], abs=0.05)


def test_decode_window_length(test_film):
    samples = decode_window(test_film, 0, 2.0, 3.0)
    assert samples.dtype.name == "float32"
    assert len(samples) == pytest.approx(48000, abs=160)
    assert 0.1 < float(abs(samples).max()) <= 1.0


def test_paths_with_spaces_and_accents(tmp_path):
    film = make_test_film(tmp_path / "Films été" / "Le Dîner (1998).mkv", duration=2.0)
    assert len(probe(film).audio) == 3
    assert len(decode_window(film, 2, 0.5, 1.0)) == pytest.approx(16000, abs=160)


def test_probe_unreadable_file_is_an_error(tmp_path):
    bad = tmp_path / "pas un film.mkv"
    bad.write_text("rien", encoding="utf-8")
    with pytest.raises(ClipsError, match="pas un film.mkv"):
        probe(bad)


def test_probe_missing_file_is_an_error(tmp_path):
    with pytest.raises(ClipsError, match="not found"):
        probe(tmp_path / "absent.mkv")


def test_missing_ffmpeg_message(monkeypatch):
    monkeypatch.setattr(media.shutil, "which", lambda name: None)
    with pytest.raises(ClipsError) as exc:
        require_ffmpeg()
    assert "brew install ffmpeg" in str(exc.value)
    assert "winget install ffmpeg" in str(exc.value)


def test_require_ffmpeg_passes_when_installed():
    require_ffmpeg()
