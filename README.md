# podcleaner-clips

[Français](README.fr.md) · **English**

A command-line tool that cuts the movie clips you noted while watching a film, and files them ready to be played live while recording a podcast episode.

> **Status: in development.** The design is settled, the code is not written yet. See the [specification](docs/spec.md) and the [implementation plan](docs/superpowers/plans/2026-11-06-podcleaner-clips-v1.md).

## What it does

While watching, you write one Markdown file per film with a timecode range and the line of each clip:

```markdown
# Le Dîner de cons
fichier: Le Diner de cons (1998).mkv
abreviation: DDC

## Extraits
- 00:12:34 > 00:12:51 | Il s'appelle Juste Leblanc
- 00:47:02 > 00:47:20 | Il a une bonne tête de vainqueur
```

Then `podcleaner-clips run notes.md`:

- always uses the French dub (VF) audio track and warns you if none is tagged as French;
- transcribes a few seconds around each clip with Whisper, finds the line and moves the start and end to sentence boundaries (up to 4 s), never cutting a word;
- adds 0.7 s fades and a transition sound, then normalizes to -16 LUFS / -1 dBTP;
- writes a 48 kHz WAV, an H.264 MP4 (black screen during the transition) and an `extraits.json` index;
- on later runs, only redoes the clips you added or changed.

```
Le Diner de cons/
  audio/DDC-01-il-s-appelle-juste-leblanc.wav
  video/DDC-01-il-s-appelle-juste-leblanc.mp4
  extraits.json
```

Lines that do not follow the clip format are ignored, so you can keep other notes in the same file.

### Options

| Option | Effect |
| --- | --- |
| `--no-transition` | Fades only, no transition sound |
| `--audio-only` | Audio clips only |
| `--video-only` | Video clips only |
| `--no-adjust` | Cut exactly at the noted timecodes, no Whisper |
| `--dry-run` | Show the proposed cuts and file names without writing anything |
| `--audio-track N` | Force an audio track when tracks are not tagged |

## No account required

Everything runs locally with ffmpeg and Whisper. If an `ANTHROPIC_API_KEY` is set, Claude suggests the film abbreviation and settles doubtful cuts. Without a key, the tool uses the title's initials and the widest safe cut.

## Requirements

- macOS or Windows
- Python 3.11 or 3.12 and [uv](https://docs.astral.sh/uv/)
- [ffmpeg](https://ffmpeg.org/) on the `PATH` (`brew install ffmpeg` / `winget install ffmpeg`)

Installation instructions will be added with the first release.

## Contributing

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md): every change goes through a pull request reviewed by the maintainer, and commits follow [Conventional Commits](https://www.conventionalcommits.org/).

## License

[MIT](LICENSE)
