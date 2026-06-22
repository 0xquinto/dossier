"""Tests for the eval-gated rollout scaffold (spec §7).

These tests cover the DETERMINISTIC parts of the eval scaffold (the row shape,
the example fixture, the metric math, the attack corpus shape) so the suite
stays green offline. The LIVE parts (A/B runner, attack harness) are
``skipif``'d on a missing ``EXA_API_KEY`` — they are blocked on keys, never
faked. With a key present, the skips lift and the skeletons raise
``NotImplementedError`` (still honest: not implemented, not fabricated).
"""

from __future__ import annotations

import pytest

from research.evals import HAVE_EXA_KEY, LIVE_BLOCKED_REASON, require_live
from research.evals.ab_runner import ABReport, ArmScore, run_ab
from research.evals.attack_harness import ATTACK_CORPUS, run_attack_suite
from research.evals.dataset import EXAMPLE_PATH, EvalRow, load_dataset

requires_key = pytest.mark.skipif(
    not HAVE_EXA_KEY, reason="blocked on keys: live eval needs EXA_API_KEY (spec §7)"
)


# --------------------------------------------------------------------------- #
# Example fixture dataset — real row shape, 2-3 rows
# --------------------------------------------------------------------------- #
def test_example_dataset_loads_with_real_row_shape():
    rows = load_dataset(EXAMPLE_PATH)
    assert 2 <= len(rows) <= 3, "example set is a 2-3 row shape reference (§7)"
    assert all(isinstance(r, EvalRow) for r in rows)
    first = rows[0]
    # The inputs that feed BOTH arms unchanged.
    assert first.company and first.role and first.url
    # The ground truth a judge scores against.
    assert first.expected_contact_name


def test_example_dataset_has_a_hard_slice():
    # CI carves hard-safety slices off tags (§7); the example shows the shape.
    tags = {t for r in load_dataset(EXAMPLE_PATH) for t in r.tags}
    assert "hard" in tags or "no-public-email" in tags


def test_default_dataset_resolves_to_example(monkeypatch):
    monkeypatch.delenv("DOSSIER_EVAL_DATASET", raising=False)
    assert load_dataset() == load_dataset(EXAMPLE_PATH)


# --------------------------------------------------------------------------- #
# Metric math — $/successful-task and the flip verdict (deterministic)
# --------------------------------------------------------------------------- #
def test_dollars_per_success_is_the_governing_metric():
    arm = ArmScore(arm="treatment", n=10, successes=5, dollars=2.50)
    assert arm.quality == pytest.approx(0.5)
    assert arm.dollars_per_success == pytest.approx(0.50)


def test_zero_successes_costs_infinity_not_div_by_zero():
    arm = ArmScore(arm="x", n=5, successes=0, dollars=1.0)
    assert arm.dollars_per_success == float("inf")
    assert arm.quality == 0.0


def test_flip_only_on_win_across_quality_and_cost():
    control = ArmScore(arm="control", n=10, successes=6, dollars=1.0)  # q=.6 $/s=.167
    better = ArmScore(arm="treatment", n=10, successes=7, dollars=1.0)  # q=.7 $/s=.143
    worse_cost = ArmScore(arm="treatment", n=10, successes=7, dollars=5.0)  # pricier
    assert ABReport(control, better).treatment_wins is True
    assert ABReport(control, worse_cost).treatment_wins is False


# --------------------------------------------------------------------------- #
# Attack corpus — deterministic shape (the dynamic execution is gated)
# --------------------------------------------------------------------------- #
def test_attack_corpus_covers_the_three_families():
    families = {c.family for c in ATTACK_CORPUS}
    assert {"prompt-injection", "pii-exfil", "label-laundering"} <= families
    assert all(c.injected_page_content and c.forbidden_outcome for c in ATTACK_CORPUS)


# --------------------------------------------------------------------------- #
# Live gating — blocked on keys, honest (skip), never faked
# --------------------------------------------------------------------------- #
def test_require_live_raises_without_key(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    # Recompute the module-level flag the function reads.
    import research.evals as evals

    monkeypatch.setattr(evals, "HAVE_EXA_KEY", False)
    with pytest.raises(RuntimeError) as exc:
        require_live()
    assert "EXA_API_KEY" in str(exc.value)


def test_blocked_reason_is_actionable():
    assert "EXA_API_KEY" in LIVE_BLOCKED_REASON
    assert "curated dataset" in LIVE_BLOCKED_REASON


def test_ab_runner_is_blocked_without_key(monkeypatch):
    # Without a key the runner must refuse loudly, not return fake numbers.
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    import research.evals as evals

    monkeypatch.setattr(evals, "HAVE_EXA_KEY", False)
    with pytest.raises(RuntimeError):
        run_ab()


def test_attack_suite_is_blocked_without_key(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    import research.evals as evals

    monkeypatch.setattr(evals, "HAVE_EXA_KEY", False)
    with pytest.raises(RuntimeError):
        run_attack_suite()


@requires_key
def test_ab_runner_live_is_a_skeleton():
    # With a key the gate lifts; the skeleton is honestly not-yet-implemented
    # (NotImplementedError), never a fabricated pass.
    with pytest.raises(NotImplementedError):
        run_ab()


@requires_key
def test_attack_suite_live_is_a_skeleton():
    with pytest.raises(NotImplementedError):
        run_attack_suite()
