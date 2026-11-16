import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx2 as httpx
import pytest

from podcleaner_clips.adjust import Word, adjust_cut
from podcleaner_clips.claude import ClaudeAdvice, ClaudeClient, _run
from podcleaner_clips.claude import find_cli as real_find_cli  # before conftest hides it
from podcleaner_clips.config import Settings

S = Settings(episodes_dir=Path("episodes"))


class FakeMessages:
    """Stands in for client.messages: answers with `answer` or raises it."""

    def __init__(self, answer):
        self.answer = answer
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.answer, Exception):
            raise self.answer
        text = self.answer if isinstance(self.answer, str) else json.dumps(self.answer)
        return SimpleNamespace(
            stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)]
        )


def fake(answer) -> SimpleNamespace:
    return SimpleNamespace(messages=FakeMessages(answer))


def lay(t0: float, text: str) -> list[Word]:
    return [Word(w, t0 + i * 0.35, t0 + i * 0.35 + 0.30) for i, w in enumerate(text.split())]


# A scene noted 100 → 120 with two sentences around the reference.
WORDS = [
    *lay(95.0, "Bon on y va."),
    *lay(101.0, "Écoute-moi bien."),
    *lay(105.0, "Je t'attends tête de bouclier."),
    *lay(112.0, "Tu le sais très bien."),
    *lay(119.0, "Allez viens."),
    *lay(126.0, "Non."),
]
FRAGMENTS = ["je t'attends tête de bouclier"]


def decision():
    return adjust_cut(WORDS, FRAGMENTS, [], 100.0, 120.0, S)


def index_of(text: str) -> int:
    return next(i for i, w in enumerate(WORDS) if w.text == text)


def test_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert not ClaudeClient(S).available


def test_unavailable_when_disabled():
    s = Settings(episodes_dir=Path("episodes"), claude_enabled=False)
    assert not ClaudeClient(s, client=fake("DDC")).available


def test_abbreviation_without_key_uses_initials(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert ClaudeClient(S).propose_abbreviation("Le Dîner de cons", None) == ("DDC", None)


def test_abbreviation_invalid_answer_falls_back():
    client = ClaudeClient(S, client=fake({"abbreviation": "Le dîner"}))
    assert client.propose_abbreviation("Le Dîner de cons", None) == ("DDC", None)


def test_abbreviation_valid_answer():
    client = ClaudeClient(S, client=fake({"abbreviation": "DDC", "reason": "initiales"}))
    abbr, advice = client.propose_abbreviation("Le Dîner de cons", "Le Diner de cons.mkv")
    assert abbr == "DDC"
    assert isinstance(advice, ClaudeAdvice)
    assert advice.kind == "abbreviation"
    assert advice.answer == "DDC"
    assert advice.reason == "initiales"
    assert advice.model == S.claude_model


def test_abbreviation_request_uses_the_configured_model():
    messages = FakeMessages({"abbreviation": "DDC", "reason": ""})
    ClaudeClient(S, client=SimpleNamespace(messages=messages)).propose_abbreviation("X", None)
    assert messages.calls[0]["model"] == S.claude_model
    assert messages.calls[0]["output_config"]["format"]["type"] == "json_schema"


def test_choose_bounds_applies_claude_choice():
    first = index_of("Écoute-moi")
    last = max(i for i, w in enumerate(WORDS) if w.text == "bien.")  # "Tu le sais très bien."
    client = ClaudeClient(
        S, client=fake({"first_word": first, "last_word": last, "reason": "scène entière"})
    )
    cut, advice = client.choose_bounds(WORDS, FRAGMENTS[0], decision(), 100.0, 120.0, S)
    assert cut.method == "claude"
    assert cut.start <= WORDS[first].start and cut.end >= WORDS[last].end
    assert advice is not None and advice.kind == "bounds"
    assert advice.reason == "scène entière"


def test_choose_bounds_keeps_heuristic_score_and_doubt():
    d = decision()
    first = index_of("Écoute-moi")
    last = max(i for i, w in enumerate(WORDS) if w.text == "bien.")
    client = ClaudeClient(S, client=fake({"first_word": first, "last_word": last, "reason": ""}))
    cut, _ = client.choose_bounds(WORDS, FRAGMENTS[0], d, 100.0, 120.0, S)
    assert cut.score == d.cut.score
    assert cut.doubt == d.cut.doubt


def test_choose_bounds_rejects_out_of_bounds():
    d = decision()
    client = ClaudeClient(S, client=fake({"first_word": 0, "last_word": 999, "reason": ""}))
    cut, advice = client.choose_bounds(WORDS, FRAGMENTS[0], d, 100.0, 120.0, S)
    assert cut == d.cut
    assert advice is not None  # the rejected opinion is still recorded


def test_choose_bounds_rejects_cut_missing_a_fragment():
    d = decision()
    first, last = index_of("Écoute-moi"), index_of("Je")  # stops inside the reference
    client = ClaudeClient(S, client=fake({"first_word": first, "last_word": last, "reason": ""}))
    cut, _ = client.choose_bounds(WORDS, FRAGMENTS[0], d, 100.0, 120.0, S)
    assert cut == d.cut


def test_choose_bounds_unavailable_keeps_decision(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    d = decision()
    assert ClaudeClient(S).choose_bounds(WORDS, FRAGMENTS[0], d, 100.0, 120.0, S) == (d.cut, None)


def test_choose_bounds_sends_numbered_words_and_notes():
    messages = FakeMessages({"first_word": 0, "last_word": 999, "reason": ""})
    client = ClaudeClient(S, client=SimpleNamespace(messages=messages))
    client.choose_bounds(WORDS, FRAGMENTS[0], decision(), 100.0, 120.0, S)
    prompt = json.dumps(messages.calls[0]["messages"], ensure_ascii=False)
    assert "bouclier" in prompt
    assert f"[{index_of('Écoute-moi')}]" in prompt
    assert "1:40" in prompt and "2:00" in prompt
    assert "(pause " in prompt  # silences between the sentences are shown


def test_choose_bounds_accepts_a_clip_centred_on_the_line():
    """Starting 5 s after the noted start, on the line itself, is allowed."""
    first, last = index_of("Je"), index_of("bouclier.")
    client = ClaudeClient(S, client=fake({"first_word": first, "last_word": last, "reason": ""}))
    cut, _ = client.choose_bounds(WORDS, FRAGMENTS[0], decision(), 100.0, 120.0, S)
    assert cut.method == "claude"
    assert cut.start <= WORDS[first].start < cut.start + 0.5


def test_bounds_system_prompt_asks_for_a_focused_clip():
    messages = FakeMessages({"first_word": 0, "last_word": 1, "reason": ""})
    ClaudeClient(S, client=SimpleNamespace(messages=messages)).choose_bounds(
        WORDS, FRAGMENTS[0], decision(), 100.0, 120.0, S
    )
    system = messages.calls[0]["system"]
    assert "punchline" in system and "setup" in system and "reaction" in system


def test_api_error_falls_back_with_warning():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    client = ClaudeClient(S, client=fake(anthropic.APIConnectionError(request=request)))
    d = decision()
    assert client.choose_bounds(WORDS, FRAGMENTS[0], d, 100.0, 120.0, S) == (d.cut, None)
    assert client.propose_abbreviation("Le Dîner de cons", None) == ("DDC", None)
    assert len(client.warnings) == 2
    assert "Claude" in client.warnings[0]


@pytest.mark.parametrize("answer", ["not json", {"first_word": "a"}, {}])
def test_malformed_bounds_answer_keeps_decision(answer):
    d = decision()
    client = ClaudeClient(S, client=fake(answer))
    assert client.choose_bounds(WORDS, FRAGMENTS[0], d, 100.0, 120.0, S)[0] == d.cut


def test_refusal_falls_back():
    d = decision()
    refusing = SimpleNamespace(
        messages=SimpleNamespace(
            create=lambda **_: SimpleNamespace(stop_reason="refusal", content=[])
        )
    )
    client = ClaudeClient(S, client=refusing)
    assert client.choose_bounds(WORDS, FRAGMENTS[0], d, 100.0, 120.0, S) == (d.cut, None)
    assert client.warnings


# Claude Code CLI backend: a fake runner stands in for subprocess.


class FakeCli:
    """Answers `claude auth status` and `claude -p` like the real CLI (--output-format json)."""

    def __init__(self, answer=None, *, logged_in=True, raises=None, stdout=None):
        self.answer, self.logged_in, self.raises, self.stdout = answer, logged_in, raises, stdout
        self.calls: list[tuple[list[str], str]] = []

    def __call__(self, args, stdin, timeout):
        self.calls.append((args, stdin))
        if args[1:3] == ["auth", "status"]:
            return subprocess.CompletedProcess(
                args, 0, json.dumps({"loggedIn": self.logged_in}), ""
            )
        if self.raises is not None:
            raise self.raises
        if self.stdout is not None:
            return subprocess.CompletedProcess(args, 1, self.stdout, "boom")
        out = {"type": "result", "is_error": False, "result": "", "structured_output": self.answer}
        return subprocess.CompletedProcess(args, 0, json.dumps(out), "")


def cli_settings(backend="auto"):
    return Settings(episodes_dir=Path("episodes"), claude_backend=backend)


def test_cli_answers_the_abbreviation(monkeypatch):
    monkeypatch.setattr("podcleaner_clips.claude.find_cli", lambda: "/bin/claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")  # the CLI still comes first
    runner = FakeCli({"abbreviation": "AV", "reason": "initials"})
    client = ClaudeClient(cli_settings(), runner=runner)

    abbr, advice = client.propose_abbreviation("Avengers", "Avengers (2012).mkv")

    assert abbr == "AV"
    assert advice == ClaudeAdvice("abbreviation", "AV", "initials", "claude-sonnet-5-5", "cli")
    assert "Claude Code CLI" in client.describe()
    args, stdin = runner.calls[-1]
    assert args[:2] == ["/bin/claude", "-p"]
    assert args[args.index("--model") + 1] == "claude-sonnet-5-5"
    assert args[args.index("--tools") + 1] == ""
    assert "--no-session-persistence" in args
    assert json.loads(args[args.index("--json-schema") + 1])["required"] == [
        "abbreviation",
        "reason",
    ]
    assert "Film title: Avengers" in stdin


def test_cli_answer_in_result_text_is_read(monkeypatch):
    out = {"type": "result", "is_error": False, "result": '{"abbreviation": "AV", "reason": ""}'}
    runner = FakeCli(stdout=json.dumps(out))
    client = ClaudeClient(S, cli="/bin/claude", runner=runner)
    assert client.propose_abbreviation("Avengers", None)[0] == "AV"


def test_cli_bounds_are_checked_like_the_api(monkeypatch):
    d = decision()
    first = index_of("Écoute-moi")
    last = max(i for i, w in enumerate(WORDS) if w.text == "bien.")
    runner = FakeCli({"first_word": first, "last_word": last, "reason": "whole scene"})
    cut, advice = ClaudeClient(S, cli="/bin/claude", runner=runner).choose_bounds(
        WORDS, FRAGMENTS[0], d, 100.0, 120.0, S
    )
    assert cut.method == "claude"
    assert advice is not None and advice.via == "cli"


@pytest.mark.parametrize(
    "runner, reason",
    [
        (FakeCli(raises=subprocess.TimeoutExpired("claude", 180)), "no answer after"),
        (FakeCli(stdout="not json"), "boom"),
        (FakeCli(stdout=json.dumps({"is_error": True, "result": "Not logged in"})), "Not logged"),
        (FakeCli(raises=FileNotFoundError("claude")), "claude"),
    ],
)
def test_cli_error_falls_back_once_for_the_whole_run(runner, reason):
    client = ClaudeClient(S, cli="/bin/claude", runner=runner)
    d = decision()
    assert client.propose_abbreviation("Le Dîner de cons", None) == ("DDC", None)
    assert client.choose_bounds(WORDS, FRAGMENTS[0], d, 100.0, 120.0, S) == (d.cut, None)
    assert len(runner.calls) == 1  # not asked again after the first failure
    assert len(client.warnings) == 1 and reason in client.warnings[0]


def test_auto_without_cli_login_uses_the_api_key(monkeypatch):
    monkeypatch.setattr("podcleaner_clips.claude.find_cli", lambda: "/bin/claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    client = ClaudeClient(cli_settings(), runner=FakeCli(logged_in=False))
    assert client.available and client.via == "api"


def test_auto_with_nothing_is_the_silent_fallback(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client = ClaudeClient(cli_settings())
    assert not client.available
    assert client.warnings == []
    assert "fallback" in client.describe()


@pytest.mark.parametrize(
    "backend, cli, logged_in, warning",
    [
        ("cli", None, True, "not installed"),
        ("cli", "/bin/claude", False, "claude auth login"),
        ("api", "/bin/claude", True, "ANTHROPIC_API_KEY"),
    ],
)
def test_forced_backend_missing_warns(monkeypatch, backend, cli, logged_in, warning):
    monkeypatch.setattr("podcleaner_clips.claude.find_cli", lambda: cli)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client = ClaudeClient(cli_settings(backend), runner=FakeCli(logged_in=logged_in))
    assert not client.available
    assert len(client.warnings) == 1 and warning in client.warnings[0]


def test_backend_off_never_runs_anything(monkeypatch):
    monkeypatch.setattr("podcleaner_clips.claude.find_cli", lambda: "/bin/claude")
    runner = FakeCli({"abbreviation": "AV", "reason": ""})
    client = ClaudeClient(cli_settings("off"), runner=runner)
    assert client.propose_abbreviation("Avengers", None) == ("AV", None)
    assert runner.calls == []


def test_cli_runs_without_the_api_key(monkeypatch, tmp_path):
    """The real runner hides ANTHROPIC_API_KEY so the CLI bills the subscription."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    done = _run(
        [sys.executable, "-c", "import os; print(os.environ.get('ANTHROPIC_API_KEY'))"], "", 30
    )
    assert done.stdout.strip() == "None"


def test_find_cli_looks_where_the_installer_puts_it(monkeypatch, tmp_path):
    folder = tmp_path / ".local" / "bin"
    folder.mkdir(parents=True)
    exe = folder / ("claude.exe" if sys.platform == "win32" else "claude")
    exe.write_text("", encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))  # not in PATH
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert Path(real_find_cli()) == exe


def test_find_cli_none_when_not_installed(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert real_find_cli() is None
