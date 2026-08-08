"""The tailor engine — asks a model for a plan and enforces the guardrails.

One corrective retry: if the returned plan points at content that doesn't exist,
or names a technology the Master CV never mentions, the violations are sent back
and a second plan is requested. A plan that fails twice raises rather than
quietly producing a CV nobody checked.

There is exactly **one** engine, holding a
:class:`~jobpilot.llm.base.StructuredClient`. That is the whole reason the
provider layer exists: the retry loop is the part that keeps a wrong plan out of
a PDF, and it must be identical no matter which company answered — a weaker
model needs it *more*, so it is the last thing that should vary by backend. When
this file had one engine class per provider, that was a promise held up by a
test; now it is held up by there being nothing to fork.

``TailorEngine`` is a Protocol so tests (and the CLI's ``--dry-run``) can swap in
``FixtureEngine`` without touching an SDK or the network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from jobpilot.cv.schema import CvDocument
from jobpilot.llm.base import Completion, LlmError, StructuredClient
from jobpilot.llm.usage import call_log
from jobpilot.store.models import Job
from jobpilot.tailor import prompt as prompts
from jobpilot.tailor.guard import GuardrailViolation, check_plan
from jobpilot.tailor.schema import TailorPlan


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


@dataclass
class ModelTailorEngine:
    """Ask a model for a plan; accept it only if the guardrails do.

    Build the prompt, check the plan, and on a violation give the model one
    corrective round with the exact list of what it broke. The client is the
    only thing that varies, and it varies in exactly one way: which company's
    API answers.

    Every round is recorded, including the rejected one. How often a backend
    needs the second round *is* its guardrail pass rate, and it is not knowable
    from the answer that eventually came back.
    """

    client: StructuredClient

    def _ask(self, system: str, messages: list[dict]) -> Completion[TailorPlan]:
        try:
            return self.client.structured(system=system, messages=messages, schema=TailorPlan)
        except LlmError as exc:
            raise TailorError(str(exc)) from exc

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

        with call_log("tailor", job_id=job.id) as usage:
            plan = usage.add_from(self._ask(system, messages))
            report = check_plan(plan, master)
            if report.ok:
                usage.succeeded()
                return TailorResult(plan=plan, attempts=1)

            # One corrective round — the model gets to see exactly what it broke.
            messages += [
                {"role": "assistant", "content": plan.model_dump_json()},
                {"role": "user", "content": prompts.retry_prompt(report.violations)},
            ]
            retried = usage.add_from(self._ask(system, messages))
            second = check_plan(retried, master)
            if not second.ok:
                raise GuardrailViolation(
                    "plan still violates the CV guardrails after one retry: "
                    + "; ".join(second.violations)
                )
            usage.succeeded()
            return TailorResult(plan=retried, attempts=2, retried_for=report.violations)


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
    from jobpilot.llm.registry import client_for

    return ModelTailorEngine(client_for("tailor"))
