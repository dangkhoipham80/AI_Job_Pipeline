"""The tailor engine — asks Claude for a plan and enforces the guardrails.

One corrective retry: if the returned plan points at content that doesn't exist,
or names a technology the Master CV never mentions, the violations are sent back
and a second plan is requested. A plan that fails twice raises rather than
quietly producing a CV nobody checked.

``TailorEngine`` is a Protocol so tests (and the CLI's ``--dry-run``) can swap in
``FixtureEngine`` without touching the Anthropic SDK or the network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from jobpilot.config import get_secrets
from jobpilot.cv.schema import CvDocument
from jobpilot.store.models import Job
from jobpilot.tailor import prompt as prompts
from jobpilot.tailor.guard import GuardrailViolation, check_plan
from jobpilot.tailor.schema import TailorPlan

# Claude Opus 4.8 with adaptive thinking; effort defaults to "high", which is
# what we want for a task this judgement-heavy.
MODEL = "claude-opus-4-8"
MAX_TOKENS = 16000


class TailorError(RuntimeError):
    """The engine could not produce a usable plan."""


@dataclass
class TailorResult:
    plan: TailorPlan
    attempts: int = 1
    retried_for: list[str] = field(default_factory=list)


class TailorEngine(Protocol):
    """Produces a validated plan for one job."""

    def tailor(
        self,
        master: CvDocument,
        job: Job,
        instruction: str | None = None,
        previous: TailorPlan | None = None,
    ) -> TailorResult: ...


class _GuardedTailor:
    """The part of tailoring that has nothing to do with which model runs it.

    Build the prompt, check the plan, and on a violation give the model one
    corrective round with the exact list of what it broke. Subclasses supply
    ``_parse`` and nothing else.

    This is a base class rather than a copied method because the alternative is
    two guardrail loops that agree today and quietly stop agreeing later — the
    same reason ``tailor/diff.py`` is parameterised by ``DiffLabels`` instead of
    being forked per caller. A local model needs the retry *more* than Claude
    does, so the two must be the same retry.
    """

    def _parse(self, system: str, messages: list[dict]) -> TailorPlan:  # pragma: no cover
        raise NotImplementedError

    def tailor(
        self,
        master: CvDocument,
        job: Job,
        instruction: str | None = None,
        previous: TailorPlan | None = None,
    ) -> TailorResult:
        system = prompts.system_prompt(master)
        user = prompts.user_prompt(job, instruction=instruction, previous=previous)
        messages: list[dict] = [{"role": "user", "content": user}]

        plan = self._parse(system, messages)
        report = check_plan(plan, master)
        if report.ok:
            return TailorResult(plan=plan, attempts=1)

        # One corrective round — the model gets to see exactly what it broke.
        messages += [
            {"role": "assistant", "content": plan.model_dump_json()},
            {"role": "user", "content": prompts.retry_prompt(report.violations)},
        ]
        retried = self._parse(system, messages)
        second = check_plan(retried, master)
        if not second.ok:
            raise GuardrailViolation(
                "plan still violates the CV guardrails after one retry: "
                + "; ".join(second.violations)
            )
        return TailorResult(plan=retried, attempts=2, retried_for=report.violations)


class ClaudeTailorEngine(_GuardedTailor):
    """Calls the Claude API and returns a guardrail-checked plan."""

    def __init__(self, api_key: str | None = None, model: str = MODEL) -> None:
        self.model = model
        self._api_key = api_key if api_key is not None else get_secrets().anthropic_api_key
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - env dependent
                raise TailorError(
                    "anthropic SDK not installed — run: pip install -e '.[tailor]'"
                ) from exc
            # An empty key here is still worth attempting: the SDK also resolves
            # ANTHROPIC_AUTH_TOKEN and an `ant auth login` profile.
            self._client = (
                anthropic.Anthropic(api_key=self._api_key)
                if self._api_key
                else anthropic.Anthropic()
            )
        return self._client

    def _parse(self, system: str, messages: list[dict]) -> TailorPlan:
        client = self._get_client()
        try:
            response = client.messages.parse(
                model=self.model,
                max_tokens=MAX_TOKENS,
                thinking={"type": "adaptive"},
                system=[
                    {
                        "type": "text",
                        "text": system,
                        # Only takes effect once the prefix clears the model's
                        # minimum cacheable size; harmless below it.
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=messages,
                output_format=TailorPlan,
            )
        except Exception as exc:  # SDK raises typed errors; surface them as one kind
            raise TailorError(f"Claude request failed: {exc}") from exc

        if response.stop_reason == "refusal":
            raise TailorError("Claude declined this request (stop_reason=refusal)")
        plan = response.parsed_output
        if plan is None:
            raise TailorError("Claude returned no parsable plan")
        return plan


class OllamaTailorEngine(_GuardedTailor):
    """The same guardrail loop, driven by a model on your own machine.

    Identical rules, identical retry — only the call differs. What changes is
    the failure profile: a smaller model breaks the guardrail more often, which
    costs an extra round rather than producing a CV that claims something
    untrue. The schema and the guard are what make that trade safe.
    """

    def __init__(self, client=None, model: str | None = None) -> None:
        from jobpilot.config import get_config
        from jobpilot.llm.ollama import OllamaClient

        cfg = get_config().llm
        self.client = client or OllamaClient(
            model=model or cfg.tailor_model or cfg.model, host=cfg.host
        )

    def _parse(self, system: str, messages: list[dict]) -> TailorPlan:
        from jobpilot.llm.ollama import OllamaError

        try:
            return self.client.structured(system=system, messages=messages, schema=TailorPlan)
        except OllamaError as exc:
            raise TailorError(str(exc)) from exc


@dataclass
class FixtureEngine:
    """Returns a canned plan — used by tests and ``cli tailor --dry-run``."""

    plan: TailorPlan
    calls: list[tuple[str, str | None]] = field(default_factory=list)

    def tailor(
        self,
        master: CvDocument,
        job: Job,
        instruction: str | None = None,
        previous: TailorPlan | None = None,
    ) -> TailorResult:
        self.calls.append((job.id, instruction))
        check_plan(self.plan, master).raise_if_bad()
        return TailorResult(plan=self.plan)


def default_engine() -> TailorEngine:
    """The engine `llm.tailor` (or `llm.provider`) asks for."""
    from jobpilot.config import get_config

    if get_config().llm.for_task("tailor") == "ollama":
        return OllamaTailorEngine()
    return ClaudeTailorEngine()
