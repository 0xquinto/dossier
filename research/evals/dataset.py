"""Eval dataset loading + the row shape (spec §7).

A dataset row is one held-out recon task with a ground-truth contact, used by
the A/B runner to score Search-API-recon vs Exa-Agent-recon on the *same*
input. ``EvalRow`` is the real shape; ``example.jsonl`` ships three rows as a
shape reference, NOT a curated eval set.

Sizing (spec §7, "pick the job, not the number"):
- ~10-12 great rows to hill-climb the architecture decision (the A/B flip).
- 100+ curated rows for the statistical CI regression gate — a 10-row suite
  cannot gate regressions at ±9pts CI (cookbook math).

The curated sets live OUTSIDE the repo (they carry real contact PII). Point the
runner at one with ``DOSSIER_EVAL_DATASET=/path/to/curated.jsonl``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

EXAMPLE_PATH = Path(__file__).parent / "fixtures" / "example.jsonl"


@dataclass(frozen=True)
class EvalRow:
    """One held-out recon task + its ground truth.

    The inputs (``company``/``role``/``url``) feed BOTH arms unchanged; the
    ``expected_*`` fields are the labelled ground truth a judge scores against.
    ``expected_email`` is the verification target — the A/B compares whether
    each arm surfaces a *fetch-verifiable* real address (spec §3), not whether a
    candidate was merely returned.
    """

    id: str
    company: str
    role: str
    url: str
    expected_contact_name: str
    expected_title: str | None = None
    expected_email: str | None = None
    # Difficulty / slice tags let the CI carve out hard-safety slices (§7).
    tags: tuple[str, ...] = ()


def _row_from_dict(d: dict) -> EvalRow:
    return EvalRow(
        id=d["id"],
        company=d["company"],
        role=d["role"],
        url=d["url"],
        expected_contact_name=d["expected_contact_name"],
        expected_title=d.get("expected_title"),
        expected_email=d.get("expected_email"),
        tags=tuple(d.get("tags", [])),
    )


def load_dataset(path: str | os.PathLike[str] | None = None) -> list[EvalRow]:
    """Load eval rows from a JSONL file.

    Resolution order: explicit ``path`` arg → ``DOSSIER_EVAL_DATASET`` env →
    the bundled ``example.jsonl`` (shape reference only). The example set is
    deliberately tiny and is NOT a curated eval set — see this module's docstring.
    """
    resolved = path or os.environ.get("DOSSIER_EVAL_DATASET") or EXAMPLE_PATH
    rows: list[EvalRow] = []
    with open(resolved, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(_row_from_dict(json.loads(line)))
    return rows
