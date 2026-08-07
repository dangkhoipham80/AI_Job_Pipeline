"""Running the pipeline on a model on your own machine.

The point of these is that no model server is needed: a fake transport stands in
for ``httpx``, so the schema, the request shape, and — most importantly — the
fact that **both providers run the identical guardrail loop** are all testable
offline.

That last one is what the tests are really for. A second engine is a second
place for the anti-fabrication rules to live, and two copies of a rule are two
rules. The loop is shared by construction; there is a test here that fails if
anyone re-forks it.
"""

from __future__ import annotations

import json

import pytest

from jobpilot.apply.inbox import Applied, MailVerdict, OllamaClassifier
from jobpilot.crawler.mailbox import MailMessage
from jobpilot.cv.sample import sample_document
from jobpilot.llm.ollama import OllamaClient, OllamaError, flatten_schema, probe
from jobpilot.store.models import Job, JobStatus
from jobpilot.tailor.engine import ClaudeTailorEngine, OllamaTailorEngine, TailorError
from jobpilot.tailor.guard import GuardrailViolation
from jobpilot.tailor.schema import TailorPlan


class FakeResponse:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text or json.dumps(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeTransport:
    """Answers /api/chat with canned replies, and remembers what was asked."""

    def __init__(self, *replies, status_code=200, tags=None):
        self.replies = list(replies)
        self.status_code = status_code
        self.tags = tags
        self.posts: list[dict] = []

    def post(self, url, json=None):
        self.posts.append(json)
        if self.status_code >= 400:
            return FakeResponse(None, self.status_code, text="boom")
        reply = self.replies.pop(0) if self.replies else self.replies
        return FakeResponse({"message": {"content": reply}})

    def get(self, url):
        if self.tags is None:
            raise RuntimeError("connection refused")
        return FakeResponse({"models": [{"name": n} for n in self.tags]})


def job() -> Job:
    return Job(
        id="itviec:1",
        source="itviec",
        url="u",
        title="Backend Engineer",
        company="ACME",
        status=JobStatus.SHORTLISTED,
        payload={"description_md": "We need a backend engineer with Java and Spring Boot."},
    )


# --------------------------------------------------------------------------- #
# the transport
# --------------------------------------------------------------------------- #
def test_the_schema_is_sent_as_a_grammar_not_a_suggestion():
    """Ollama compiles `format` into a decoding grammar, which is why a small
    model can be trusted with a structured reply at all."""
    t = FakeTransport(MailVerdict(verdict="replied", quote="hi").model_dump_json())
    client = OllamaClient(model="qwen2.5:7b", transport=t)
    client.structured(system="s", messages=[{"role": "user", "content": "u"}], schema=MailVerdict)

    sent = t.posts[0]
    assert sent["format"]["type"] == "object"
    assert sent["stream"] is False
    assert sent["options"]["temperature"] == 0  # ranking, not creative writing
    assert sent["messages"][0] == {"role": "system", "content": "s"}


def test_nested_models_are_inlined_for_the_grammar_compiler():
    """Pydantic hoists nested models into `$defs` and points at them with
    `$ref`. References are the shakiest corner of schema-to-grammar, and these
    schemas are small and non-recursive, so inlining costs nothing."""
    flat = flatten_schema(TailorPlan.model_json_schema())
    blob = json.dumps(flat)
    assert "$defs" not in blob and "$ref" not in blob
    # And the nested shape survived: a requirement still has its enum.
    assert "must_have" in blob


def test_a_reply_that_does_not_fit_the_schema_is_an_error_not_a_guess():
    t = FakeTransport('{"verdict": "replied"')  # truncated
    client = OllamaClient(model="m", transport=t)
    with pytest.raises(OllamaError):
        client.structured(system="s", messages=[], schema=MailVerdict)


def test_a_missing_model_says_how_to_get_it():
    t = FakeTransport(status_code=404)
    client = OllamaClient(model="qwen2.5:7b", transport=t)
    with pytest.raises(OllamaError, match="ollama pull qwen2.5:7b"):
        client.structured(system="s", messages=[], schema=MailVerdict)


def test_an_unreachable_server_says_so_before_anything_is_queued():
    """Same courtesy as the email gates: report the blocker now, not as a task
    that dies a minute later."""
    assert "ollama serve" in probe(OllamaClient(model="m", transport=FakeTransport()))
    assert "not pulled" in probe(
        OllamaClient(model="llama3", transport=FakeTransport(tags=["qwen2.5:7b"]))
    )
    assert probe(OllamaClient(model="qwen2.5", transport=FakeTransport(tags=["qwen2.5:7b"]))) == ""


# --------------------------------------------------------------------------- #
# the guardrail is the same guardrail
# --------------------------------------------------------------------------- #
def test_both_providers_share_one_guardrail_loop():
    """The whole reason the loop was extracted. If someone re-implements
    `tailor()` on either engine, this fails."""
    assert OllamaTailorEngine.tailor is ClaudeTailorEngine.tailor


def test_a_local_plan_is_checked_exactly_like_a_claude_one():
    master = sample_document()
    # COBOL is nowhere on the sample CV; Kubernetes is, which is why the
    # guardrail is right to stay quiet about it.
    bad = TailorPlan(match_score=0.8, summary="I led COBOL migrations at scale.")
    t = FakeTransport(bad.model_dump_json(), bad.model_dump_json())

    engine = OllamaTailorEngine(client=OllamaClient(model="m", transport=t))
    with pytest.raises(GuardrailViolation):
        engine.tailor(master, job())

    # Two attempts: the local model got the same corrective round Claude gets.
    assert len(t.posts) == 2
    assert "rejected" in json.dumps(t.posts[1]["messages"]).lower()


def test_a_clean_local_plan_is_accepted():
    master = sample_document()
    plan = TailorPlan(match_score=0.8, summary="")
    t = FakeTransport(plan.model_dump_json())

    result = OllamaTailorEngine(client=OllamaClient(model="m", transport=t)).tailor(master, job())
    assert result.attempts == 1


def test_a_dead_server_surfaces_as_a_tailor_error():
    """Callers already handle `TailorError`; a backend swap must not make them
    learn a second exception type."""
    engine = OllamaTailorEngine(
        client=OllamaClient(model="m", transport=FakeTransport(status_code=500))
    )
    with pytest.raises(TailorError):
        engine.tailor(sample_document(), job())


# --------------------------------------------------------------------------- #
# the classifier — the easiest of the three
# --------------------------------------------------------------------------- #
def test_the_local_classifier_returns_a_verdict():
    mail = MailMessage(
        uid="1",
        subject="Re: your application",
        sender="anna@acme.com",
        date=None,
        html="",
        text="We would like to invite you to a technical interview.",
    )
    verdict = MailVerdict(verdict="interview", quote="we would like to invite you")
    t = FakeTransport(verdict.model_dump_json())

    out = OllamaClassifier(client=OllamaClient(model="m", transport=t)).classify(
        mail, Applied(1, "itviec:1", "ACME", "Backend Engineer")
    )
    assert out.verdict == "interview"


def test_the_quote_guard_still_applies_to_a_local_verdict():
    """`check_verdict` runs in `sync_inbox`, not in the engine — so a weaker
    model shows up as a dropped suggestion, never as a wrong outcome."""
    from jobpilot.apply.inbox import check_verdict

    mail = MailMessage(uid="1", subject="s", sender="a@b.com", date=None, html="", text="Hello.")
    invented = MailVerdict(verdict="offer", quote="we are delighted to offer you the role")
    assert "does not appear" in " ".join(check_verdict(invented, mail))


# --------------------------------------------------------------------------- #
# choosing a provider
# --------------------------------------------------------------------------- #
def test_provider_is_chosen_per_task(monkeypatch):
    """The usual shape is a local classifier and a paid letter — that is where
    the money buys the most."""
    from jobpilot.config import LlmCfg

    cfg = LlmCfg(provider="claude", classify="ollama")
    assert cfg.for_task("classify") == "ollama"
    assert cfg.for_task("letter") == "claude"
    assert cfg.for_task("tailor") == "claude"

    everything_local = LlmCfg(provider="ollama")
    assert [everything_local.for_task(t) for t in ("tailor", "letter", "classify")] == [
        "ollama"
    ] * 3


def test_a_task_can_pin_its_own_model():
    from jobpilot.config import LlmCfg

    cfg = LlmCfg(model="qwen2.5:7b", tailor_model="qwen2.5:14b")
    assert cfg.model_for("tailor") == "qwen2.5:14b"
    assert cfg.model_for("classify") == "qwen2.5:7b"


def test_the_shipped_config_is_what_it_claims_to_be():
    """Two different defaults, and conflating them gives false confidence.

    The Python class defaults to `claude` — that is the fallback for anyone
    constructing `LlmCfg` directly. But `config.yaml` is what users actually
    run, and it ships `classify: ollama` because that call was measured at 5/5
    while tailor was 0/4. Asserting only the class default would let the shipped
    file drift to something nobody reviewed.
    """
    from jobpilot.config import LlmCfg, get_config

    assert LlmCfg().provider == "claude"

    shipped = get_config().llm
    assert shipped.provider == "claude"
    assert shipped.for_task("classify") == "ollama"  # the one measured good enough
    assert shipped.for_task("tailor") == "claude"  # 0/4 locally — see PLAN.md §9.1
    assert shipped.for_task("letter") == "claude"


def test_a_local_task_is_blocked_before_it_is_queued(monkeypatch):
    """`probe` used to be documented as a pre-flight check that nothing called.
    Now the inbox route and the task body both ask, so a stopped `ollama serve`
    is a 409 rather than a job that dies a minute later."""
    from jobpilot import llm
    from jobpilot.config import Config, LlmCfg

    cfg = Config()
    cfg.llm = LlmCfg(provider="ollama", host="http://127.0.0.1:1")  # nothing listening
    monkeypatch.setattr("jobpilot.config.get_config", lambda *a, **k: cfg)

    assert "ollama" in llm.blocker("classify").lower()
    # Claude has no equivalent pre-flight — a bad key costs a request to find.
    cfg.llm = LlmCfg(provider="claude")
    assert llm.blocker("classify") == ""
