# Changelog

[Français](CHANGELOG.fr.md) · **English**

All notable changes to podcleaner-clips. Versions follow [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-19

First public version. podcleaner-clips cuts the clips you noted while watching a film (start timecode, a few words of the line, end timecode) and files them as WAV and MP4, ready to be played live while recording a podcast episode.

### Highlights

- **Notes written the way you take them.** One line per clip, such as `42:30 vas-y, je t'attends, tête de bouclier 42:40`. `HH:MM:SS` and `MM:SS` both work, and so do `6;25` and `25 min 30`. A line can hold several fragments, separated by `…`, `...` or ` - `. The tool ignores the other lines.
- **Always the French dub.** The tool picks the VF track, VFF rather than VFQ when the film has both (adjustable), and warns you when no track is tagged French. `--audio-track N` overrides a mislabelled track.
- **Cuts that never fall in the middle of a line.** The tool finds each line in the French subtitles, then in the dub with Whisper (`large-v3-turbo`, only around each clip, never the whole film). Every cut lands on a sentence boundary, between two words.
- **Claude centres the clip on the line.** Your timecodes are read as a rough area and the noted line as the moment that matters. Claude keeps just the setup needed to get the joke and the reaction that follows, and checks are applied to its answer. It is reached through your Claude subscription (Claude Code CLI) or an API key; the default model is `claude-sonnet-5-5`. Without Claude, the cut goes on the sentence boundary closest to each timecode.
- **Ready to play live.** Each clip has 0.7 s fades, with your transition sound before and after it. After the last word, the line gets a 0.5 s pause before the fade-out and the closing transition start (`pad_after_s`). The film sound is at -16 LUFS, the transition sound at -19 LUFS (`lufs` / `transition_lufs`, or `--lufs` / `--transition-lufs`), never above -1 dBTP. The tool writes a 48 kHz 24-bit stereo WAV and an H.264 + AAC MP4. In the MP4, the transition plays over a black screen or your own transition video, and the picture fades in from black and out to black with the sound.
- **Fast reruns.** Only clips you add or change are redone. Files of clips that move are renamed; files of clips you remove are listed, never deleted. A new transition video only redoes the MP4s. Cuts and Claude's opinions are kept in `clips.json`.
- **Easy setup.** Install with `uv tool install git+https://github.com/IvesPower/podcleaner-clips`. Commands: `podcleaner-clips` or `pclips`, then `init`, `run`, `config`, `version`. `pclips init` asks a few questions and writes a commented configuration file.
- **macOS and Windows.** Paths handled with `pathlib`, UTF-8 text, CI on both systems.

### Changes for users of the 0.1.0 development version

- Configuration, notes header and index now use English keys (`episodes_dir`, `file:`, `clips.json`…). The old French names (`dossier_episodes`, `fichier:`, `extraits.json`…) are still read, with a notice that asks you to rename them.
- The transition sound is no longer mixed at the clip's level. It now has its own loudness (`transition_lufs`, -19 LUFS by default): reruns redo every clip once.
- The fade-out no longer starts on the last word: a pause (`pad_after_s`, now 0.5 s) comes first, then the fade. When the next line starts sooner, the film sound stops just before it with a shorter, S-shaped fade, the picture goes on and fades to black until the transition, and the transition still waits for the pause.
- Claude's default model is now `claude-sonnet-5-5` instead of `claude-haiku-5-5`, and its cuts may be tighter than your timecodes.

### Requirements

- macOS or Windows, [uv](https://docs.astral.sh/uv/) (Python 3.11 or 3.12), [ffmpeg](https://ffmpeg.org/) on the `PATH`.
- Optional: a Claude subscription with [Claude Code](https://claude.com/claude-code), or an `ANTHROPIC_API_KEY`.

### Not in this version

- No live player.
- No video transition effects other than the fade to black and the transition video.
- No subtitles in the clips.

[1.0.0]: https://github.com/IvesPower/podcleaner-clips/releases/tag/v1.0.0
