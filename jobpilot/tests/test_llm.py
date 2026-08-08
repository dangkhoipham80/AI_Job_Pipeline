"""Choosing a model backend, and the things that must not vary when you do.

No network and no SDK: a fake ``StructuredClient`` stands in for the provider, so
the guardrail loop, the schema dialects, the cost accounting and the pre-flight
check are all testable offline.

The tests worth reading twice are the ones about *sameness*. Three backends is
three places for the anti-fabrication rules to drift apart, and two copies of a
rule are two rules. There is exactly one tailor engine and one letter engine, and
the tests below fail if that stops being true.
"""

from __future__ import annotations

import json

import pytest

from jobpilot.apply.inbox import Applied, MailVerdict, ModelClassifier
from jobpilot.apply.letter import CoverLetter, ModelLetterEngine
from jobpilot.crawler.mailbox import MailMessage
from jobpilot.cv.sample import sample_document
from jobpilot.llm.base import Completion, LlmError, Usage
from jobpilot.llm.pricing import PRICES, estimate_cost, policy_for
from jobpilot.llm.schema import flatten_schema, strictify
from jobpilot.store.models import Job, JobStatus
from jobpilot.tailor.engine import ModelTailorEngine, TailorError
from jobpilot.tailor.guard import GuardrailViolation
from jobpilot.tailor.schema import TailorPlan


class FakeClient:
    """Answers with canned objects and remembers what it was asked."""

    provider = "fake"
    model = "fake-1"

    def __init__(self, *replies, error: Exception | None = None, usage: Usage | None = None):
        self.replies = list(replies)
        self.error = error
        self.usage = usage
        self.calls: list[dict] = []

    def structured(self, *, system, messages, schema):
        self.calls.append({"system": system, "messages": list(messages), "schema": schema})
        if self.error is not None:
            raise self.error
        reply = self.replies.pop(0)
        usage = self.usage or Usage(
            input_tokens=100, output_tokens=10, provider=self.provider, model=self.model
        )
        return Completion(value=reply, usage=usage)


@pytest.fixture(autouse=True)
def _no_telemetry(monkeypatch):
    """The engines record every round; these tests are about the engines.

    Recording opens its own session, and ``record`` already swallows failures —
    but silently relying on that would make every test here depend on a database
    being absent, which is the kind of accident ``test_slack`` was caught by.
    """
    recorded: list = []
    monkeypatch.setattr("jobpilot.llm.usage.record", recorded.append)
    return recorded


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
# schema dialects
# --------------------------------------------------------------------------- #
def test_nested_models_are_inlined_for_providers_that_dislike_refs():
    """Pydantic hoists nested models into `$defs` and points at them with
    `$ref`. Gemini documents only a subset of JSON Schema and warns that deep or
    large schemas may be rejected, so it gets the flattened form — the same
    treatment, for the same reason, that made a local grammar compiler workable.
    """
    flat = flatten_schema(TailorPlan.model_json_schema())
    blob = json.dumps(flat)
    assert "$defs" not in blob and "$ref" not in blob
    # And the nested shape survived: a requirement still has its enum.
    assert "must_have" in blob


def test_strict_mode_requires_every_property_and_forbids_extras():
    """OpenAI strict mode demands `additionalProperties: false` and every
    property in `required`."""
    strict = strictify(flatten_schema(TailorPlan.model_json_schema()))

    def check(node):
        if isinstance(node, list):
            for item in node:
                check(item)
            return
        if not isinstance(node, dict):
            return
        props = node.get("properties")
        if isinstance(props, dict):
            assert node["additionalProperties"] is False
            assert set(props) == set(node["required"])
        for value in node.values():
            check(value)

    check(strict)


def test_an_optional_field_becomes_nullable_rather_than_mandatory():
    """The dangerous reading of "every property must be required" is that a
    field the plan may legally omit becomes one the model has to invent. Strict
    mode's actual position is that absence is spelled `null`, and this repo
    cannot afford to get that backwards.
    """
    schema = {
        "type": "object",
        "properties": {"summary": {"type": "string"}, "score": {"type": "number"}},
        "required": ["score"],
    }
    out = strictify(schema)
    assert set(out["required"]) == {"summary", "score"}
    assert out["properties"]["summary"]["type"] == ["string", "null"]
    # The already-required one is untouched.
    assert out["properties"]["score"]["type"] == "number"


# --------------------------------------------------------------------------- #
# one guardrail loop, whoever answers
# --------------------------------------------------------------------------- #
def test_a_plan_from_any_backend_gets_the_same_corrective_round():
    master = sample_document()
    # COBOL is nowhere on the sample CV; the guardrail is right to reject it.
    bad = TailorPlan(match_score=0.8, summary="I led COBOL migrations at scale.")
    client = FakeClient(bad, bad)

    with pytest.raises(GuardrailViolation):
        ModelTailorEngine(client).tailor(master, job())

    assert len(client.calls) == 2
    assert "rejected" in json.dumps(client.calls[1]["messages"]).lower()


def test_a_clean_plan_is_accepted_on_the_first_round():
    client = FakeClient(TailorPlan(match_score=0.8, summary=""))
    result = ModelTailorEngine(client).tailor(sample_document(), job())
    assert result.attempts == 1


def test_a_dead_backend_surfaces_as_a_tailor_error():
    """Callers already handle `TailorError`; swapping provider must not make
    them learn a second exception type."""
    engine = ModelTailorEngine(FakeClient(error=LlmError("402 no credit")))
    with pytest.raises(TailorError, match="no credit"):
        engine.tailor(sample_document(), job())


def test_the_letter_engine_retries_on_the_same_terms_as_the_tailor():
    """Until Phase 20b this file held two near-identical copies of the loop, one
    per provider. One engine, one loop — and it still retries once."""
    master = sample_document()
    unsupported = CoverLetter(
        greeting="Dear ACME,",
        paragraphs=["I have shipped production COBOL for eight years."],
        closing="Regards,",
    )
    client = FakeClient(unsupported, unsupported)
    with pytest.raises(GuardrailViolation):
        ModelLetterEngine(client).write(master, job())
    assert len(client.calls) == 2


# --------------------------------------------------------------------------- #
# the classifier — the easiest of the three
# --------------------------------------------------------------------------- #
def test_the_classifier_returns_a_verdict():
    mail = MailMessage(
        uid="1",
        subject="Re: your application",
        sender="anna@acme.com",
        date=None,
        html="",
        text="We would like to invite you to a technical interview.",
    )
    client = FakeClient(MailVerdict(verdict="interview", quote="we would like to invite you"))
    out = ModelClassifier(client).classify(mail, Applied(1, "itviec:1", "ACME", "Backend Engineer"))
    assert out.verdict == "interview"


def test_the_quote_guard_still_applies_to_any_verdict():
    """`check_verdict` runs in `sync_inbox`, not in the engine — so a weaker
    model shows up as a dropped suggestion, never as a wrong outcome."""
    from jobpilot.apply.inbox import check_verdict

    mail = MailMessage(uid="1", subject="s", sender="a@b.com", date=None, html="", text="Hello.")
    invented = MailVerdict(verdict="offer", quote="we are delighted to offer you the role")
    assert "does not appear" in " ".join(check_verdict(invented, mail))


# --------------------------------------------------------------------------- #
# choosing a provider
# --------------------------------------------------------------------------- #
def test_provider_is_chosen_per_task():
    """The three calls differ enough in difficulty that one backend for all of
    them is a coincidence, not a design."""
    from jobpilot.config import LlmCfg

    cfg = LlmCfg(provider="claude", classify="gemini")
    assert cfg.for_task("classify") == "gemini"
    assert cfg.for_task("letter") == "claude"
    assert cfg.for_task("tailor") == "claude"

    everything = LlmCfg(provider="openai")
    assert [everything.for_task(t) for t in ("tailor", "letter", "classify")] == ["openai"] * 3


def test_an_unknown_provider_is_refused_at_config_time():
    """The failure mode this replaces is a typo that reads as "no override" and
    silently runs the default backend."""
    from jobpilot.config import LlmCfg

    with pytest.raises(ValueError, match="unknown provider"):
        LlmCfg(provider="gpt4")
    with pytest.raises(ValueError, match="unknown provider"):
        LlmCfg(tailor="anthropik")


def test_a_task_can_pin_a_cheaper_model_than_its_provider_default():
    """Classify is six labels and one quoted sentence; Phase 20 showed a local
    7B got it 5/5. Paying flagship rates for it is a choice, and this is where
    the choice is expressed."""
    from jobpilot.config import LlmCfg

    cfg = LlmCfg(
        provider="claude",
        models={"claude": "claude-opus-4-8"},
        task_models={"classify": "claude-haiku-4-5"},
    )
    assert cfg.model_for("tailor") == "claude-opus-4-8"
    assert cfg.model_for("classify") == "claude-haiku-4-5"

    # No entry anywhere falls back to the provider's own default, so switching
    # backend does not require knowing model ids.
    assert LlmCfg(provider="gemini").model_for("tailor").startswith("gemini-")


def test_the_shipped_config_is_what_it_claims_to_be():
    """Two different defaults, and conflating them gives false confidence.

    The Python class defaults to `claude`; `config.yaml` is what users actually
    run. Asserting only the class default would let the shipped file drift to a
    backend nobody reviewed — which, for these three calls, means changing what
    someone's job applications say.

    Reads ``config.yaml`` directly rather than ``get_config()``, which merges the
    developer's ``config.local.yaml`` over it. Asserting on the merged value makes
    this test pass or fail depending on which backend the person running it
    happens to have selected — the same machine-dependence that
    ``test_missing_tokens_produce_a_readable_error`` was caught by in Phase 20,
    and it caught this test too.
    """
    import yaml

    from jobpilot.config import CONFIG_PATH, LlmCfg

    assert LlmCfg().provider == "claude"

    shipped = LlmCfg(**(yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")).get("llm") or {}))
    assert shipped.provider == "claude"
    assert [shipped.for_task(t) for t in ("tailor", "letter", "classify")] == ["claude"] * 3


def test_a_task_with_no_api_key_is_blocked_before_it_is_queued(monkeypatch):
    """Same courtesy the email gates extend: report the blocker now, not as a
    task that dies a minute later with the same message."""
    from jobpilot import llm
    from jobpilot.config import Config, LlmCfg, Secrets

    cfg = Config()
    cfg.llm = LlmCfg(provider="openai")
    monkeypatch.setattr("jobpilot.config.get_config", lambda *a, **k: cfg)
    monkeypatch.setattr("jobpilot.config.get_secrets", lambda *a, **k: Secrets(openai_api_key=""))

    blocked = llm.blocker("classify")
    assert "OPENAI_API_KEY" in blocked

    monkeypatch.setattr(
        "jobpilot.config.get_secrets", lambda *a, **k: Secrets(openai_api_key="sk-test")
    )
    assert llm.blocker("classify") == ""


# --------------------------------------------------------------------------- #
# what a call cost, and what the provider may do with it
# --------------------------------------------------------------------------- #
def test_an_unpriced_model_costs_None_not_zero():
    """A price table goes stale by sitting still. $0.00 for a model nobody
    priced would make the least-known backend the cheapest-looking one —
    precisely backwards, and precisely the column people sort by."""
    assert estimate_cost("claude", "claude-opus-4-8", 1_000_000, 0) == pytest.approx(5.0)
    assert estimate_cost("openai", "gpt-9-imaginary", 1_000_000, 1_000_000) is None
    assert estimate_cost("nobody", "nothing", 10, 10) is None


def test_every_priced_model_has_both_rates():
    for key, rate in PRICES.items():
        assert len(rate) == 2, key
        assert all(r > 0 for r in rate), key


def test_only_the_free_gemini_tier_warns_and_it_names_the_cv(monkeypatch):
    """The narrow true statement, not a warning sprayed at every provider.

    Anthropic, OpenAI and *paid* Gemini all say they do not train on API input.
    The unpaid Gemini tier says it does, and its terms say in as many words not
    to send personal information — which is what `tailor` sends, entirely.
    """
    from jobpilot import llm
    from jobpilot.config import Config, LlmCfg

    assert policy_for("claude").trains_on_input is False
    assert policy_for("gemini", paid_tier=True).trains_on_input is False
    assert policy_for("gemini", paid_tier=False).trains_on_input is True

    cfg = Config()
    monkeypatch.setattr("jobpilot.config.get_config", lambda *a, **k: cfg)

    cfg.llm = LlmCfg(provider="gemini", gemini_paid_tier=True)
    assert llm.warnings("tailor") == []

    cfg.llm = LlmCfg(provider="gemini", gemini_paid_tier=False)
    warned = " ".join(llm.warnings("tailor"))
    assert "Master CV" in warned
    assert "ai.google.dev" in warned

    # Classify sends mail, not the CV — the warning must say the right thing.
    assert "Master CV" not in " ".join(llm.warnings("classify"))


def test_every_round_is_banked_including_the_rejected_one(monkeypatch):
    """A backend that is cheap per call and needs two rounds half the time is
    not cheap. A log that only kept the accepted round would hide exactly that.
    """
    entries: list = []
    monkeypatch.setattr("jobpilot.llm.usage.record", entries.append)

    bad = TailorPlan(match_score=0.8, summary="I led COBOL migrations at scale.")
    with pytest.raises(GuardrailViolation):
        ModelTailorEngine(FakeClient(bad, bad)).tailor(sample_document(), job())

    assert len(entries) == 1
    entry = entries[0]
    assert entry.task == "tailor"
    assert entry.attempts == 2
    assert entry.accepted is False  # the guard never accepted anything
    assert entry.job_id == "itviec:1"

    entries.clear()
    ModelTailorEngine(FakeClient(TailorPlan(match_score=0.8, summary=""))).tailor(
        sample_document(), job()
    )
    assert entries[0].accepted is True and entries[0].attempts == 1


# --------------------------------------------------------------------------- #
# reading the log back as a decision
# --------------------------------------------------------------------------- #
def _call(db, **kwargs):
    from jobpilot.store.models import LlmCall

    row = LlmCall(
        **{
            "task": "tailor",
            "provider": "openai",
            "model": "gpt-4.1",
            "round": 1,
            "ok": True,
            "input_tokens": 1000,
            "output_tokens": 100,
            "latency_ms": 500,
            "cost_usd": 0.001,
            **kwargs,
        }
    )
    db.add(row)
    return row


def test_a_small_sample_reports_counts_not_percentages(session_factory):
    """Three calls with two failures is not "33% success", it is three calls.

    A percentage invites a comparison, and comparing two backends on three calls
    each is how a coin flip becomes a decision. Below MIN_SAMPLE the rates are
    withheld and the caller shows ``attempts``.
    """
    from jobpilot.llm.stats import MIN_SAMPLE, backend_stats

    with session_factory() as db:
        for _ in range(3):
            _call(db)
        db.commit()
        rows = backend_stats(db)

    assert rows[0]["attempts"] == 3
    assert rows[0]["first_try_rate"] is None
    assert rows[0]["success_rate"] is None

    with session_factory() as db:
        for _ in range(MIN_SAMPLE):
            _call(db)
        db.commit()
        rows = backend_stats(db)

    assert rows[0]["attempts"] == 3 + MIN_SAMPLE
    assert rows[0]["success_rate"] == 1.0


def test_a_retry_costs_two_rounds_but_counts_as_one_attempt(session_factory):
    """The whole reason rounds are rows: a backend that is cheap per call and
    retries half the time is not cheap. Both rounds bill; only one task ran."""
    from jobpilot.llm.stats import MIN_SAMPLE, backend_stats

    with session_factory() as db:
        for _ in range(MIN_SAMPLE - 1):
            _call(db)  # clean, first try
        _call(db, round=1)  # the one that needed help...
        _call(db, round=2)  # ...and the round that fixed it
        db.commit()
        rows = backend_stats(db)

    row = rows[0]
    assert row["attempts"] == MIN_SAMPLE
    assert row["rounds"] == MIN_SAMPLE + 1
    assert row["success_rate"] == 1.0
    # Nine of ten landed without a corrective round.
    assert row["first_try_rate"] == pytest.approx((MIN_SAMPLE - 1) / MIN_SAMPLE)


def test_unpriced_rounds_are_counted_not_quietly_summed_as_zero(session_factory):
    """A total built from half the rows gets read as if it covered all of them,
    so the number of rows it *didn't* cover travels with it."""
    from jobpilot.llm.stats import backend_stats

    with session_factory() as db:
        _call(db, cost_usd=0.01)
        _call(db, cost_usd=None)
        db.commit()
        rows = backend_stats(db)

    assert rows[0]["cost_usd"] == pytest.approx(0.01)
    assert rows[0]["unpriced_rounds"] == 1

    # Nothing priced at all is None, not 0.0 — see estimate_cost.
    with session_factory() as db:
        _call(db, model="gpt-9-imaginary", cost_usd=None)
        db.commit()
        rows = {r["model"]: r for r in backend_stats(db)}

    assert rows["gpt-9-imaginary"]["cost_usd"] is None


def test_backends_are_kept_apart_by_task_provider_and_model(session_factory):
    """The comparison is meaningless if a cheap classify model is averaged into
    the tailor row that shares its provider."""
    from jobpilot.llm.stats import backend_stats

    with session_factory() as db:
        _call(db, task="tailor", provider="claude", model="claude-opus-4-8")
        _call(db, task="classify", provider="claude", model="claude-haiku-4-5")
        _call(db, task="classify", provider="openai", model="gpt-4.1-mini")
        db.commit()
        assert len(backend_stats(db)) == 3
        assert {r["task"] for r in backend_stats(db, task="classify")} == {"classify"}


def test_a_task_that_retried_and_still_failed_does_not_drag_down_first_try_rate(session_factory):
    """The bug this pins was a real 70%-instead-of-80% in review.

    ``first_try`` is ``successes - successes that retried``. Count *every* retry
    instead and a task that retried and failed — which was never in the success
    count — cancels out an unrelated task that got it right first time. Both
    halves of a subtraction have to be counting the same population.

    Wrong in the worst direction, too: it under-reports first-try accuracy in
    the one table built for choosing between backends.
    """
    from jobpilot.llm.stats import MIN_SAMPLE, backend_stats

    clean = MIN_SAMPLE - 2
    with session_factory() as db:
        for _ in range(clean):
            _call(db, round=1, ok=True)
        _call(db, round=1, ok=True)  # retried, then fine
        _call(db, round=2, ok=True)
        _call(db, round=1, ok=False)  # retried, still rejected
        _call(db, round=2, ok=False)
        db.commit()
        row = backend_stats(db)[0]

    assert row["attempts"] == MIN_SAMPLE
    assert row["first_try_rate"] == pytest.approx(clean / MIN_SAMPLE)
    assert row["success_rate"] == pytest.approx((clean + 1) / MIN_SAMPLE)


def test_first_try_rate_survives_a_backend_that_only_ever_fails(session_factory):
    """The `max(..., 0)` in the sum used to hide the miscount rather than fix
    it; with every task failing there is nothing to hide behind."""
    from jobpilot.llm.stats import MIN_SAMPLE, backend_stats

    with session_factory() as db:
        for _ in range(MIN_SAMPLE):
            _call(db, round=1, ok=False)
            _call(db, round=2, ok=False)
        db.commit()
        row = backend_stats(db)[0]

    assert row["attempts"] == MIN_SAMPLE
    assert row["success_rate"] == 0.0
    assert row["first_try_rate"] == 0.0


# --------------------------------------------------------------------------- #
# credentials must not survive a trip through an error message
# --------------------------------------------------------------------------- #
def test_a_provider_that_quotes_your_key_back_does_not_get_it_stored(monkeypatch):
    """This is not hypothetical. A bad OpenAI key answers with
    ``Incorrect API key provided: sk-proj-...`` — and that string becomes an
    LlmError, a TailorError, a row in `llm_calls.error`, a CLI line, and an API
    field. Scrubbing happens where the error is *created*, because there is one
    of those and an unbounded number of places it ends up.
    """
    from jobpilot.config import Secrets
    from jobpilot.llm.base import LlmError
    from jobpilot.llm.redact import redact

    key = "sk-proj-AAAABBBBCCCCDDDDEEEEFFFFGGGGHHHH"
    monkeypatch.setattr("jobpilot.config.get_secrets", lambda *a, **k: Secrets(openai_api_key=key))

    leaked = f"OpenAI request failed: 401 - Incorrect API key provided: {key}"
    assert key not in str(LlmError(leaked))
    assert "[redacted]" in str(LlmError(leaked))

    # And the shape guard catches keys this process never held — a partially
    # masked echo, or a provider added later whose secret is not in Secrets.
    assert "sk-ant-" not in redact("Error: sk-ant-api03-ZZZZYYYYXXXXWWWW rejected")
    assert "AIza" not in redact("key=AIzaSyD-000000000000000000000000000")
    assert "sk-proj-****" not in redact("Incorrect API key provided: sk-proj-****abcd")


def test_a_database_url_password_is_scrubbed_too():
    """`database_url` carries a password and shows up in connection errors —
    the same column, the same durability, the same problem."""
    from jobpilot.llm.redact import redact

    url = "postgresql+psycopg://postgres:hunter2secret@127.0.0.1:5432/jobpilot"
    assert "hunter2secret" not in redact(f"could not connect: {url}")


def test_the_stats_api_never_carries_key_material():
    """The dashboard shows which provider runs what and whether it is blocked.
    'Blocked' must be a fact about configuration, not a quotation of it."""
    import re

    from jobpilot.api.schemas import BackendStatsOut, LlmStatsOut, ProviderSpendOut

    # A rule, not a snapshot of the field list: a snapshot fails every time the
    # page grows a feature, which trains people to update it without reading it.
    # This fails only when a field arrives whose name says it carries a secret.
    # Name AND type. A credential can only live in a string: `has_key: bool`
    # answers "is one configured" and `input_tokens: int` is a count — neither
    # can carry the thing. Flagging those would be noise, and a check that cries
    # wolf is a check people mute.
    secretish = re.compile(r"(?i)key|token|secret|password|credential")
    for model in (LlmStatsOut, ProviderSpendOut, BackendStatsOut):
        named = [
            name
            for name, field in model.model_fields.items()
            if secretish.search(name) and "str" in str(field.annotation)
        ]
        assert named == [], f"{model.__name__} exposes {named}"

    # `error` holds provider exception text — exactly where a rejected key gets
    # quoted back. It stays out of anything the API returns.
    assert "error" not in BackendStatsOut.model_fields


def test_a_traceback_does_not_leak_the_key_the_provider_quoted_back(monkeypatch):
    """The leak the security review found, and the subtlest one here.

    ``LlmError`` scrubs its own *message*, but it is raised ``from`` the SDK
    exception — and that original still quotes the rejected key verbatim. Any
    renderer that walks ``__cause__`` (a traceback) prints it again. So
    ``str(exc)`` is safe while ``traceback.format_exc()`` is not, and the
    orchestrator logs the latter on every failed task.
    """
    import traceback

    from jobpilot.config import Secrets
    from jobpilot.llm.base import LlmError
    from jobpilot.llm.redact import redact

    key = "sk-proj-AAAABBBBCCCCDDDDEEEEFFFFGGGGHHHH"
    monkeypatch.setattr("jobpilot.config.get_secrets", lambda *a, **k: Secrets(openai_api_key=key))

    try:
        try:
            raise RuntimeError(f"Incorrect API key provided: {key}")
        except RuntimeError as sdk_error:
            raise LlmError(f"OpenAI request failed: {sdk_error}") from sdk_error
    except LlmError:
        rendered = traceback.format_exc()

    # The chain really does still carry it — this is the thing being defended.
    assert key in rendered
    assert key not in redact(rendered)


def test_settings_cannot_smuggle_a_secret_into_the_overlay():
    """`PUT /settings` merges the *raw* patch into config.local.yaml, and
    Pydantic ignores unknown fields rather than rejecting them — so validation
    passed while a live key went to disk. Pruning happens before the merge, and
    covers every section, not just the one that was noticed.
    """
    from jobpilot.config import Config, prune_to_schema

    pruned = prune_to_schema(
        Config,
        {
            "llm": {"classify": "openai", "anthropic_api_key": "sk-proj-SECRET"},
            "apply": {"email": {"enabled": True, "smtp_password": "hunter2secret"}},
            "not_a_section": {"whatever": 1},
        },
    )
    assert pruned == {"llm": {"classify": "openai"}, "apply": {"email": {"enabled": True}}}


def test_a_sibling_model_does_not_vouch_for_a_withdrawn_one():
    """Prefix matching exists for Anthropic's dated snapshots. Left loose it
    also lets `gemini-3.5-flash-lite` mark `gemini-3.5-flash` as available —
    reporting a withdrawn model as usable, which is the failure direction this
    repo cares about most."""
    from jobpilot.api.routes.stats import _offered

    assert _offered("claude-haiku-4-5", ["claude-haiku-4-5-20251001"])  # dated snapshot
    assert _offered("gemini-3.5-flash", ["gemini-3.5-flash"])  # exact
    assert not _offered("gemini-3.5-flash", ["gemini-3.5-flash-lite"])  # a different model
    assert not _offered("gpt-4o-mini", ["gpt-4o"])
    assert _offered("anything", [])  # we didn't ask; absence of evidence
