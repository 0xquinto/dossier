"""A/B runner skeleton: Search-API-recon vs Exa-Agent-recon (spec §7).

Compares the two recon arms on the SAME held-out dataset and reports quality
**and** ``$/successful-task`` per arm. The default flips to the Exa Agent only
on a measured win across both axes (spec §7 "A/B before flip").

    Arm A (control):  Search-API recon  — exa-py contents / search, multi-call
    Arm B (treatment): Exa-Agent recon  — ExaAgentClient.run_recon(...)

>>> BLOCKED ON KEYS <<<
Both arms hit the live Exa API, so a real ``EXA_API_KEY`` is required, plus a
curated dataset (the bundled example.jsonl is a shape reference, not an eval
set). This module is a SKELETON: ``run_ab`` raises via ``require_live()`` until
keys + dataset are wired. It NEVER fabricates a result.

TODO(blocked-on-keys):
  - implement ``_run_search_api_arm`` against exa-py search/contents
  - implement ``_run_exa_agent_arm`` via ExaAgentClient.run_recon
  - implement ``_judge`` (LLM-judge or exact-match on expected_* ground truth)
  - wire a curated >=100-row dataset for the CI regression gate
"""

from __future__ import annotations

from dataclasses import dataclass, field

from research.evals import require_live
from research.evals.dataset import EvalRow, load_dataset


@dataclass
class ArmScore:
    """Per-arm rollup over the dataset (spec §5/§7 governing metric)."""

    arm: str
    n: int = 0
    successes: int = 0  # tasks with a fetch-verifiable correct contact
    dollars: float = 0.0  # metered on EVERY task, incl. failures (§5)

    @property
    def quality(self) -> float:
        """Fraction of tasks resolved (pass^k target, not pass@1; §7)."""
        return self.successes / self.n if self.n else 0.0

    @property
    def dollars_per_success(self) -> float:
        """The governing metric — $ / *successful* task, never $ / token (§5)."""
        return self.dollars / self.successes if self.successes else float("inf")


@dataclass
class ABReport:
    """The win/no-win verdict the flip decision reads."""

    control: ArmScore
    treatment: ArmScore
    notes: list[str] = field(default_factory=list)

    @property
    def treatment_wins(self) -> bool:
        """Flip only on a win across quality AND $/task (spec §7)."""
        return (
            self.treatment.quality >= self.control.quality
            and self.treatment.dollars_per_success <= self.control.dollars_per_success
        )


def _run_search_api_arm(row: EvalRow) -> ArmScore:  # pragma: no cover - blocked on keys
    """TODO(blocked-on-keys): control arm via exa-py search/contents."""
    raise NotImplementedError("Search-API arm — blocked on EXA_API_KEY + dataset.")


def _run_exa_agent_arm(row: EvalRow) -> ArmScore:  # pragma: no cover - blocked on keys
    """TODO(blocked-on-keys): treatment arm via ExaAgentClient.run_recon."""
    raise NotImplementedError("Exa-Agent arm — blocked on EXA_API_KEY + dataset.")


def _judge(row: EvalRow, result) -> bool:  # pragma: no cover - blocked on keys
    """TODO(blocked-on-keys): score a result against the row's ground truth.

    Success = the arm surfaced a *fetch-verifiable* correct contact (spec §3):
    name match AND, where ``expected_email`` is set, a verified (own-fetched,
    verbatim) address — never a provider-asserted candidate.
    """
    raise NotImplementedError("Judge — blocked on a curated dataset + key.")


def run_ab(dataset_path: str | None = None) -> ABReport:
    """Run both arms over the dataset and return the flip verdict.

    >>> BLOCKED ON KEYS <<< Calls ``require_live()`` first, so this raises with
    an actionable message until a real key is present — it does not fake numbers.
    """
    require_live()  # raises RuntimeError(LIVE_BLOCKED_REASON) without a key
    rows = load_dataset(dataset_path)  # noqa: F841 - used once arms are implemented
    raise NotImplementedError(  # pragma: no cover - blocked on keys
        "A/B runner is a skeleton: implement the two arms + judge (see TODOs)."
    )
