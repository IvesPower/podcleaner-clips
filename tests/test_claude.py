import json
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx2 as httpx
import pytest

from podcleaner_clips.adjust import Word, adjust_cut
from podcleaner_clips.claude import ClaudeAdvice, ClaudeClient
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
    *lay(105.0, "Ce bébé c'est une connerie."),
    *lay(112.0, "Tu le sais très bien."),
    *lay(119.0, "Allez viens."),
    *lay(126.0, "Non."),
]
FRAGMENTS = ["ce bébé c'est une connerie"]


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
    client = ClaudeClient(S, client=fake({"abreviation": "Le dîner"}))
    assert client.propose_abbreviation("Le Dîner de cons", None) == ("DDC", None)


def test_abbreviation_valid_answer():
    client = ClaudeClient(S, client=fake({"abreviation": "DDC", "raison": "initiales"}))
    abbr, advice = client.propose_abbreviation("Le Dîner de cons", "Le Diner de cons.mkv")
    assert abbr == "DDC"
    assert isinstance(advice, ClaudeAdvice)
    assert advice.kind == "abreviation"
    assert advice.answer == "DDC"
    assert advice.reason == "initiales"
    assert advice.model == S.claude_model


def test_abbreviation_request_uses_the_configured_model():
    messages = FakeMessages({"abreviation": "DDC", "raison": ""})
    ClaudeClient(S, client=SimpleNamespace(messages=messages)).propose_abbreviation("X", None)
    assert messages.calls[0]["model"] == S.claude_model
    assert messages.calls[0]["output_config"]["format"]["type"] == "json_schema"


def test_choose_bounds_applies_claude_choice():
    first = index_of("Écoute-moi")
    last = max(i for i, w in enumerate(WORDS) if w.text == "bien.")  # "Tu le sais très bien."
    client = ClaudeClient(
        S, client=fake({"premier_mot": first, "dernier_mot": last, "raison": "scène entière"})
    )
    cut, advice = client.choose_bounds(WORDS, FRAGMENTS[0], decision(), 100.0, 120.0, S)
    assert cut.method == "claude"
    assert cut.start <= WORDS[first].start and cut.end >= WORDS[last].end
    assert advice is not None and advice.kind == "bornes"
    assert advice.reason == "scène entière"


def test_choose_bounds_keeps_heuristic_score_and_doubt():
    d = decision()
    first = index_of("Écoute-moi")
    last = max(i for i, w in enumerate(WORDS) if w.text == "bien.")
    client = ClaudeClient(S, client=fake({"premier_mot": first, "dernier_mot": last, "raison": ""}))
    cut, _ = client.choose_bounds(WORDS, FRAGMENTS[0], d, 100.0, 120.0, S)
    assert cut.score == d.cut.score
    assert cut.doubt == d.cut.doubt


def test_choose_bounds_rejects_out_of_bounds():
    d = decision()
    client = ClaudeClient(S, client=fake({"premier_mot": 0, "dernier_mot": 999, "raison": ""}))
    cut, advice = client.choose_bounds(WORDS, FRAGMENTS[0], d, 100.0, 120.0, S)
    assert cut == d.cut
    assert advice is not None  # the rejected opinion is still recorded


def test_choose_bounds_rejects_cut_missing_a_fragment():
    d = decision()
    first, last = index_of("Écoute-moi"), index_of("Ce")  # stops inside the reference
    client = ClaudeClient(S, client=fake({"premier_mot": first, "dernier_mot": last, "raison": ""}))
    cut, _ = client.choose_bounds(WORDS, FRAGMENTS[0], d, 100.0, 120.0, S)
    assert cut == d.cut


def test_choose_bounds_unavailable_keeps_decision(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    d = decision()
    assert ClaudeClient(S).choose_bounds(WORDS, FRAGMENTS[0], d, 100.0, 120.0, S) == (d.cut, None)


def test_choose_bounds_sends_numbered_words_and_notes():
    messages = FakeMessages({"premier_mot": 0, "dernier_mot": 999, "raison": ""})
    client = ClaudeClient(S, client=SimpleNamespace(messages=messages))
    client.choose_bounds(WORDS, FRAGMENTS[0], decision(), 100.0, 120.0, S)
    prompt = json.dumps(messages.calls[0]["messages"], ensure_ascii=False)
    assert "connerie" in prompt
    assert f"[{index_of('Écoute-moi')}]" in prompt
    assert "1:40" in prompt and "2:00" in prompt


def test_api_error_falls_back_with_warning():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    client = ClaudeClient(S, client=fake(anthropic.APIConnectionError(request=request)))
    d = decision()
    assert client.choose_bounds(WORDS, FRAGMENTS[0], d, 100.0, 120.0, S) == (d.cut, None)
    assert client.propose_abbreviation("Le Dîner de cons", None) == ("DDC", None)
    assert len(client.warnings) == 2
    assert "Claude" in client.warnings[0]


@pytest.mark.parametrize("answer", ["not json", {"premier_mot": "a"}, {}])
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
