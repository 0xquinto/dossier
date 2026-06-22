"""Eval-gated rollout for the Exa Agent swap (spec §7).

This package is a SKELETON: the live A/B comparison and the dynamic
injection/PII attack harness both require a real ``EXA_API_KEY`` and a curated
dataset, neither of which ships in the repo. Everything that would touch the
network is gated behind ``require_live()`` so the deterministic suite stays
green and honest — no faked results, ever.

See ``research/evals/README.md`` for the two-tier CI intent and eval sizing.
"""

from __future__ import annotations

import os

# A field is "live" only when a real key is present. Tests import this and skip
# (never fake) when it is False.
HAVE_EXA_KEY = bool(os.environ.get("EXA_API_KEY"))

LIVE_BLOCKED_REASON = (
    "BLOCKED ON KEYS: live eval needs EXA_API_KEY + a curated dataset. "
    "This is a TODO scaffold (spec §7); it never fabricates results."
)


def require_live() -> None:
    """Raise if a live run is attempted without a key.

    The runner skeletons call this before any network work so an accidental
    invocation fails loudly with the actionable reason instead of silently
    producing fake numbers.
    """
    if not HAVE_EXA_KEY:
        raise RuntimeError(LIVE_BLOCKED_REASON)
