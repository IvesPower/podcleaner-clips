"""End-to-end smoke test of podcleaner-clips on a generated film.

Builds a 20 s test film (VFF 660 Hz, original 440 Hz, VFQ 880 Hz), a notes file with two
clips in the real format, a transition sound and a throwaway config, then runs the CLI:

1. `run --no-adjust`: cut at the noted timecodes;
2. `run` (Whisper), unless --no-whisper;
3. the same run again: every clip must be "unchanged".

After each run that renders, checks names, durations, loudness and the dub (the VFF's
660 Hz must dominate). Prints one PASS/FAIL line per check; exit code 1 if any fails.

Usage (from the repository root):
    uv run python .claude/skills/test-rapide/scripts/smoke_test.py [--no-whisper]
        [--folder-name NAME] [--keep]
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))

from make_test_film import make_test_film  # noqa: E402

from podcleaner_clips.naming import parse_tc  # noqa: E402
from podcleaner_clips.render_audio import ClipLayout, measure_loudness  # noqa: E402

FADE_S = 0.7
TRANSITION_S = 1.0
CLIPS = [(3.0, 8.0, "bonjour tout le monde"), (12.0, 16.0, "au revoir les amis")]
NAMES = ["TF-01-bonjour-tout-le-monde", "TF-02-au-revoir-les-amis"]
VFF_HZ = 660

failures: list[str] = []


def report(ok: bool, what: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {what}")
    if not ok:
        failures.append(what)


def cli(*args: str) -> subprocess.CompletedProcess:
    code = (
        "import sys; from podcleaner_clips.cli import main; "
        "sys.argv[0] = 'podcleaner-clips'; main()"
    )
    return subprocess.run(
        [sys.executable, "-c", code, *args], capture_output=True, text=True, encoding="utf-8"
    )


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return float(json.loads(out)["format"]["duration"])


def dominant_hz(wav: Path, start: float, length: float) -> float:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(start), "-t", str(length), "-i", str(wav),
         "-ac", "1", "-ar", "48000", "-f", "f32le", "-"],
        check=True,
        capture_output=True,
    ).stdout  # fmt: skip
    x = np.frombuffer(raw, dtype=np.float32)
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.fft.rfftfreq(len(x), 1 / 48000)[int(np.argmax(spectrum))])


def check_outputs(out: Path, label: str) -> None:
    index = out / "extraits.json"
    clips = json.loads(index.read_text(encoding="utf-8"))["extraits"] if index.is_file() else []
    report(len(clips) == 2, f"{label}: extraits.json lists the 2 clips")
    for clip, name in zip(clips, NAMES, strict=False):
        # Expected length from the cut actually chosen (Whisper may move the bounds).
        cut = clip["retenu"]
        layout = ClipLayout(parse_tc(cut["debut"]), parse_tc(cut["fin"]), FADE_S, TRANSITION_S)
        wav, mp4 = out / "audio" / f"{name}.wav", out / "video" / f"{name}.mp4"
        report(wav.is_file() and mp4.is_file(), f"{label}: {name}.wav and .mp4 written")
        if not wav.is_file() or not mp4.is_file():
            continue
        for path in (wav, mp4):
            d = duration(path)
            report(
                abs(d - layout.total_s) <= 0.1,
                f"{label}: {path.name} lasts {d:.2f} s (expected {layout.total_s:.2f})",
            )
        lufs, peak = measure_loudness(wav)
        report(-17.0 <= lufs <= -15.0, f"{label}: {wav.name} at {lufs:.1f} LUFS (target -16)")
        report(peak <= -0.9, f"{label}: {wav.name} true peak {peak:.1f} dBTP (max -1)")
        hz = dominant_hz(wav, layout.film_offset + FADE_S + 0.5, 1.0)
        report(abs(hz - VFF_HZ) < 15, f"{label}: dominant {hz:.0f} Hz = VFF track ({VFF_HZ} Hz)")


def run_and_check(args: list[str], label: str, out: Path, *, expect_unchanged: bool) -> None:
    proc = cli("run", *args)
    report(proc.returncode == 0, f"{label}: exit code {proc.returncode}")
    if proc.returncode != 0:
        print(proc.stdout + proc.stderr)
        return
    lines = [line for line in proc.stdout.splitlines() if line.startswith(("01 ", "02 "))]
    if expect_unchanged:
        ok = len(lines) == 2 and all(line.endswith("unchanged") for line in lines)
        report(ok, f"{label}: both clips unchanged, nothing redone")
    else:
        check_outputs(out, label)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--no-whisper", action="store_true", help="Skip the Whisper run.")
    parser.add_argument("--folder-name", default="smoke", help="Folder holding everything.")
    parser.add_argument("--keep", action="store_true", help="Keep the files for listening.")
    opts = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="podcleaner-smoke-"))
    root = tmp / opts.folder_name
    root.mkdir()
    try:
        film = make_test_film(root / "films" / "test film.mkv", duration=20.0)
        transition = root / "transition.wav"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
             f"sine=frequency=330:duration={TRANSITION_S}", "-ac", "2", str(transition)],
            check=True,
        )  # fmt: skip
        episodes = root / "épisodes"
        config = root / "config.toml"
        config.write_text(
            # json.dumps quotes like TOML: apostrophes and accents in paths are fine.
            f"dossier_episodes = {json.dumps(episodes.as_posix(), ensure_ascii=False)}\n"
            f"son_transition = {json.dumps(transition.as_posix(), ensure_ascii=False)}\n"
            "[claude]\nactif = false\n",
            encoding="utf-8",
        )
        notes = root / "notes" / "test film.md"
        notes.parent.mkdir()
        lines = [f"fichier: {film.as_posix()}", ""]
        lines += [f"{int(s) // 60}:{int(s) % 60:02d} {ref} {int(e) // 60}:{int(e) % 60:02d}"
                  for s, e, ref in CLIPS]  # fmt: skip
        notes.write_text("\n".join(lines) + "\n", encoding="utf-8")
        out = episodes / "test film"
        base = [str(notes), "--config", str(config)]

        run_and_check([*base, "--no-adjust"], "no-adjust", out, expect_unchanged=False)
        report("abreviation: TF" in notes.read_text(encoding="utf-8"), "abbreviation in notes")
        if opts.no_whisper:
            run_and_check([*base, "--no-adjust"], "rerun", out, expect_unchanged=True)
        else:
            run_and_check(base, "whisper", out, expect_unchanged=False)
            run_and_check(base, "rerun", out, expect_unchanged=True)
    finally:
        if opts.keep:
            print(f"\nFiles kept in {root}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{'All checks passed.' if not failures else f'{len(failures)} check(s) failed.'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
