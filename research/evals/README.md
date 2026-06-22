# Eval-gated rollout — Exa Agent swap (spec §7)

The Search-API → Exa-Agent swap ships **eval-gated, not on vibes**. This
directory is the scaffold for that gate. It is **blocked on keys**: the live
parts need a real `EXA_API_KEY` and curated datasets that do not ship in the
repo. Nothing here fabricates results — live entrypoints raise via
`require_live()`, and the live tests `skipif` on a missing key.

## What's here

| File | Role | Status |
|---|---|---|
| `dataset.py` | `EvalRow` shape + JSONL loader | ready (deterministic) |
| `fixtures/example.jsonl` | three rows showing the real row shape | ready (shape ref, **not** a curated set) |
| `ab_runner.py` | A/B: Search-API-recon vs Exa-Agent-recon | **skeleton — blocked on keys** |
| `attack_harness.py` | dynamic injection/PII attack slice | **skeleton — blocked on keys** |
| `../../tests/test_evals_scaffold.py` | deterministic coverage + live skips | ready |

## Two-tier CI intent

Per `eval-driven-development.md` + `observability-stack.md`:

1. **Fast deterministic PR gate** — runs on every PR, no network.
   - **Hard-safety slices, zero failures block merge:**
     - the rewritten `tests/test_provenance_contract.py` (fabrication /
       PII-adjacent contract).
     - the **dynamic injection/PII attack harness** (`attack_harness.py`) —
       AgentDojo / InjecAgent / Promptfoo-style. The static contract test is
       **not** a substitute for dynamic injection testing; both run.
   - The deterministic eval-scaffold tests (`test_evals_scaffold.py`) — row
     shape, metric math, attack-corpus shape.
   - **Zero-fail semantics:** any breach in a safety slice fails the PR, full
     stop. Quality regressions are gated separately (below).

2. **Nightly comprehensive suite** — needs `EXA_API_KEY`, runs the live arms.
   - LLM-judges + **`pass^k` not `pass@1`** for the reliability SLO.
   - **Cost is a CI metric** (`$/successful-task`, never `$/token`); gate on the
     CI **lower bound**, not the point estimate.
   - The A/B (`ab_runner.py`) decides the flip: switch the default to the Exa
     Agent only on a measured win across **quality AND $/task**.
   - Production failures feed back into the curated dataset **weekly**.

The existing **108+ tests stay green** as the regression floor.

## Eval sizing — pick the job, not the number

Two datasets, two jobs (`eval-driven-development.md`):

- **~10-12 great evals** to *hill-climb* the architecture decision (the A/B
  flip). Small, hand-curated, high-signal.
- **100+ curated examples** for the *statistical CI regression gate*. The
  cookbook CI math: a 10-eval suite cannot gate regressions at ±9pts CI, so the
  regression gate needs the larger set.

The example fixture here is **3 rows** — a shape reference only, neither set.

## Running (once keys + datasets exist)

```bash
export EXA_API_KEY=...                       # blocked-on-keys gate
export DOSSIER_EVAL_DATASET=/path/curated.jsonl   # curated, NOT in repo (PII)

python -c "from research.evals.ab_runner import run_ab; print(run_ab())"
python -c "from research.evals.attack_harness import run_attack_suite; run_attack_suite()"
```

Both currently raise `NotImplementedError` after the key gate — honest
skeletons. See the `TODO(blocked-on-keys)` markers in each module for the
implementation checklist.

## Why datasets live outside the repo

Curated recon rows carry **real contact PII** (the one-way boundary in the
node charter). The repo ships only the synthetic `*.example.com` shape
reference; real sets are pointed at via `DOSSIER_EVAL_DATASET`.
