---
name: compat-windows
description: Pre-release Windows compatibility check for podcleaner-clips - scans the code for text files opened without encoding, hard-coded paths and shell=True, checks ffmpeg, runs the tool in a folder with accents and an apostrophe, and reads the Windows CI results. Use it before every release or version tag, when the user asks whether the tool works on Windows, or after changes to file handling, paths, subprocess calls or the CLI, even if Windows is not named ("ready to release?", "check compatibility").
---

# Windows compatibility check

The tool is developed on macOS but must work the same on Windows. The usual breakages are silent on a Mac: a text file read without `encoding=` works on macOS (UTF-8 by default) and garbles accents on Windows (cp1252); a path written as `/Users/...` or joined with `/` by hand; `shell=True`, which quotes differently in cmd.exe; accented folder names. Run every step below, then report.

## 1. Scan the code

```bash
uv run python scripts/check_windows_compat.py src
uv run python scripts/check_windows_compat.py scripts
```

Each problem is printed as `file:line: message`; exit code 1 when something is found. Fix by adding `encoding="utf-8"` (or `"utf-8-sig"` for files a user may have saved with a BOM), taking the path from the configuration or building it with `pathlib`, and passing a list of arguments instead of `shell=True`.

## 2. ffmpeg is found

```bash
uv run python -c "from podcleaner_clips.media import require_ffmpeg; require_ffmpeg(); print('ffmpeg OK')"
```

## 3. Run in an awkward folder

Accents and an apostrophe in every path (notes, film, output, config), as on a real French Windows machine:

```bash
uv run python .claude/skills/test-rapide/scripts/smoke_test.py --no-whisper --folder-name "Été à l'écran"
```

All lines must be `PASS`. This runs `run --no-adjust` and a rerun; see the test-rapide skill for what each check means.

## 4. Windows CI

The CI runs the tests on `windows-latest` with Python 3.11 and 3.12 (`.github/workflows/ci.yml`). Check the latest run on `main`:

```bash
gh run list --branch main --workflow CI --limit 3
```

If the last run failed, open it (`gh run view <id> --log-failed`) and report the Windows job's error.

## Report

One line per step (OK, or the problems found with `file:line`), then a verdict: ready for Windows, or what must be fixed first. Only the user's own Windows machine can confirm the real thing: suggest they run step 3 there before a release if it has not been done.
