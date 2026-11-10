---
name: test-rapide
description: End-to-end smoke test of podcleaner-clips on a generated 20 s film (notes file, config, `run --no-adjust`, `run` with Whisper, rerun), checking clip names, durations, loudness (-16 LUFS, -1 dBTP) and that the French dub track was used. Use it whenever the user asks to check that the tool still works end to end, wants a quick test, a smoke test, "test rapide", or before opening a pull request that touches the pipeline, rendering, notes, naming or index, even if they only say "check it still works".
---

# Quick end-to-end test

The unit tests (`uv run pytest`) check each module apart. This test runs the real command line on a real (generated) film, the way a user would, and listens to the result with numbers: it catches what only shows when the pieces are put together (wrong track, wrong length, level off, a rerun that redoes everything).

## Run it

From the repository root:

```bash
uv run python .claude/skills/test-rapide/scripts/smoke_test.py
```

What the script does, so you can explain a failure:

1. Generates a 20 s film with `scripts/make_test_film.py`: VFF at 660 Hz, original at 440 Hz, VFQ at 880 Hz, and a 1 s transition sound at 330 Hz.
2. Writes a notes file with two clips in the real format (`0:03 bonjour tout le monde 0:08`) and a throwaway config (`[claude] actif = false`, so no network).
3. Runs `run --no-adjust`, then `run` (Whisper), then `run` again. After each run that renders, it checks:
   - `TF-01-….wav` / `.mp4` and `TF-02-….wav` / `.mp4` exist, and `extraits.json` lists 2 clips;
   - each file lasts the expected length (cut + transitions, ±0.1 s), computed from the cut recorded in the index;
   - each WAV is at -16 ± 1 LUFS with a true peak ≤ -1 dBTP;
   - the dominant frequency in the middle of each clip is 660 Hz: the VFF track was chosen, not the VFQ or the original;
   - `abreviation: TF` was written into the notes;
   - the last run says `unchanged` for both clips (nothing redone).
4. Prints one `PASS` / `FAIL` line per check and exits with code 1 if any check failed. Everything is written in a temporary folder and deleted at the end.

Options:

- `--no-whisper`: skip the Whisper run (no model download; about 20 s instead of a minute). Use it when the change cannot affect locating the lines, or on a machine without the model.
- `--keep`: keep the generated files and print their folder, to listen to a clip.
- `--folder-name NAME`: name of the folder holding everything (the compat-windows skill uses an accented name).

The test film is made of sine waves, so Whisper finds no words: the Whisper run keeps the noted timecodes and flags "reference not found". That is expected; what this run checks is that the Whisper path runs end to end.

## Report

Tell the user in a few lines: how many checks passed, and for each `FAIL` the line as printed, what it means (for example "dominant 880 Hz: the VFQ was used instead of the VFF") and the likely place in the code (`media.choose_audio_track`, `render_audio`, `index.plan_actions`…). Do not fix anything unless asked.
