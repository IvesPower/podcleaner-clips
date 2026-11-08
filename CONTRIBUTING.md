# Contributing

[Français](CONTRIBUTING.fr.md) · **English**

## Workflow

- `main` is protected: nobody pushes to it directly, and force-pushes and deletion are blocked.
- Every change goes through a pull request. A PR from a contributor is merged only after the maintainer approves it (see [CODEOWNERS](.github/CODEOWNERS)).
- Work on a branch named after its type: `feat/notes-parser`, `fix/track-selection`, `docs/readme`.

## Commit messages

Commits follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<optional scope>): <description>
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`, `chore`. A breaking change adds `!` after the type (`feat!: …`) or a `BREAKING CHANGE:` footer.

Examples:

```
feat(notes): read timecodes with milliseconds
fix(audio): keep the dialogue when downmixing a 5.1 track
docs: translate the specification into English
```

## Documentation

Docs exist in English and French. English files have no suffix (`README.md`), French files end in `.fr.md` (`README.fr.md`). When you change one, update the other in the same PR, or say in the PR that the translation is pending.

## Pull request description

Every PR starts with a **TL;DR**: 1 to 3 plain sentences saying what the PR changes and why, understandable without reading the code. The [PR template](.github/pull_request_template.md) is filled in automatically when you open a PR: TL;DR, changes, testing, notes.

## Before opening a PR

```bash
uv run ruff check
uv run pytest
```

Both must pass on macOS and Windows; CI checks both.
