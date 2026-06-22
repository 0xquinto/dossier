"""Shared Exa Agent client for the dossier research agents (spec §2, §3, §5).

One Python client wraps the Exa Agent endpoint (``agent.runs.create`` →
``poll_until_finished``) and is reached the same way by both faces (CLI and the
SaaS sandbox). It holds the two research jobs (``run_recon`` / ``run_discover``),
the Pydantic ``outputSchema`` wiring, reliability primitives (per-attempt
timeout, retry ceiling, circuit breaker, run-ID idempotency), and cost
accounting with the three hard stops.

Design constraints carried from the spec:

- **§3 grounding leads, never verifies.** The client returns ``(result,
  grounding, cost)``. ``grounding`` is a separate audit trace; the client NEVER
  stamps a field ``verified`` — that label is earned later by the agent's own
  full-page fetch. No code path here writes a confidence flag.
- **§2 errors are prompts.** Typed exceptions carry recovery text for the
  missing key, the rate-limit / 2-concurrent cap, and a cost-cap hit.
- **§5 meter on failure.** Errored/empty runs are still charged to the
  accountant, or ``$/successful-task`` is unenforceable.

``exa_py`` is lazy-imported only inside the default client factory, so unit
tests run with an injected fake and no real package or network.
"""

from __future__ import annotations

import concurrent.futures
import os
from typing import Any, Callable

from board_aggregator.exa_schemas import (
    DiscoverResult,
    ReconResult,
    json_schema,
)

# Pricing reference (Exa Agent API guide): 1 ACU = $0.10, $0.005/search,
# $0.02/email, $0.07/phone. We read the run's own costDollars when present and
# only fall back to component math if the breakdown is absent.

_DEFAULT_READ_RETRIES = 3
_DEFAULT_WRITE_RETRIES = 1
_DEFAULT_BREAKER_THRESHOLD = 5
_DEFAULT_POLL_INTERVAL_MS = 4000
_DEFAULT_TIMEOUT_S = 600
# Exa allows 2 concurrent Agent runs at default QPS (one fifth of account QPS).
_CONCURRENCY_AT_DEFAULT_QPS = 2


# --------------------------------------------------------------------------- #
# Typed errors (errors-as-prompts, §2)
# --------------------------------------------------------------------------- #
class ExaAgentError(Exception):
    """Base class for Exa Agent client errors."""


class MissingApiKeyError(ExaAgentError):
    """No EXA_API_KEY available for the default client factory."""

    def __init__(self) -> None:
        super().__init__(
            "EXA_API_KEY is not set. The Exa Agent client needs an Exa API key. "
            "Set it in your environment (e.g. `export EXA_API_KEY=...`) or pass an "
            "already-built exa-py client via ExaAgentClient(client=...). "
            "Onboarding (primer-8) configures this during setup."
        )


class ExaTimeoutError(ExaAgentError):
    """A single attempt blew past the per-attempt wall-clock timeout."""

    def __init__(self, timeout_s: float) -> None:
        super().__init__(
            f"An Exa Agent attempt did not finish within {timeout_s:.0f}s. "
            "Long Agent runs can stall on a slow poll. The attempt was abandoned "
            "and retried under the retry ceiling; if you see this at the cap, the "
            "run is likely stuck — lower effort/maxItems, raise timeout_s "
            "deliberately, or check Exa availability before retrying."
        )


class RateLimitError(ExaAgentError):
    """Exa rate-limited or refused for concurrency (2 concurrent at default QPS)."""

    def __init__(self) -> None:
        super().__init__(
            "Exa rate-limited this run. The Agent concurrency limit is "
            f"{_CONCURRENCY_AT_DEFAULT_QPS} active runs at default QPS. "
            "Serialize runs or wait for an in-flight run to finish before retrying."
        )


class CostCapExceeded(ExaAgentError):
    """A hard cost stop fired (max runs, per-run, or per-day dollar ceiling)."""


class NoProgressError(ExaAgentError):
    """Consecutive runs made no progress — abort rather than burn compute."""


class CircuitBreakerOpen(ExaAgentError):
    """Too many consecutive failures; the breaker is open and short-circuits."""

    def __init__(self) -> None:
        super().__init__(
            "Exa Agent circuit breaker is open after repeated failures. "
            "Stopping further calls to avoid runaway cost. Investigate Exa "
            "availability / credentials before resetting."
        )


# --------------------------------------------------------------------------- #
# Cost accounting (§5): three hard stops + meter-on-failure
# --------------------------------------------------------------------------- #
class CostAccountant:
    """Tracks spend across runs and enforces the three hard stops.

    Stops (any one aborts):
      1. ``max_runs`` — ceiling on runs this phase.
      2. ``no_progress_limit`` — consecutive no-progress runs.
      3. ``per_run_cap`` / ``per_day_cap`` — dollar ceilings.

    Every charged run (including failed/empty ones) is metered before the caps
    are evaluated, so ``$/successful-task`` stays computable.
    """

    def __init__(
        self,
        max_runs: int = 50,
        per_run_cap: float = 2.0,
        per_day_cap: float = 50.0,
        no_progress_limit: int = 3,
    ) -> None:
        self.max_runs = max_runs
        self.per_run_cap = per_run_cap
        self.per_day_cap = per_day_cap
        self.no_progress_limit = no_progress_limit

        self.run_count = 0
        self.failed_count = 0
        self.total_dollars = 0.0
        self._consecutive_no_progress = 0

    def precheck(self) -> None:
        """Raise before starting a run if a run-count or day cap is already hit."""
        if self.run_count >= self.max_runs:
            raise CostCapExceeded(
                f"Max runs reached ({self.run_count}/{self.max_runs}). "
                "Raise the ceiling deliberately or stop the phase."
            )
        if self.total_dollars >= self.per_day_cap:
            raise CostCapExceeded(
                f"Per-day spend cap reached (${self.total_dollars:.2f} / "
                f"${self.per_day_cap:.2f}). Aborting."
            )

    def charge(
        self,
        run_id: str,
        dollars: float,
        made_progress: bool,
        succeeded: bool = True,
    ) -> None:
        """Meter a finished run (always), then enforce the post-run caps.

        Metering happens first so a run that trips a cap is still counted
        (meter-on-failure). Failed runs are metered too.
        """
        self.run_count += 1
        self.total_dollars += dollars
        if not succeeded:
            self.failed_count += 1

        if made_progress:
            self._consecutive_no_progress = 0
        else:
            self._consecutive_no_progress += 1

        # Hard stops, evaluated after metering.
        if dollars > self.per_run_cap:
            raise CostCapExceeded(
                f"Run {run_id} cost ${dollars:.2f}, over the per-run cap of "
                f"${self.per_run_cap:.2f}. Aborting."
            )
        if self.total_dollars > self.per_day_cap:
            raise CostCapExceeded(
                f"Per-day spend cap exceeded (${self.total_dollars:.2f} / "
                f"${self.per_day_cap:.2f}) after run {run_id}. Aborting."
            )
        if self._consecutive_no_progress >= self.no_progress_limit:
            raise NoProgressError(
                f"{self._consecutive_no_progress} consecutive runs made no "
                "progress. Aborting to avoid burning compute on a stuck task."
            )

    def as_dict(self) -> dict[str, Any]:
        """Cost summary for meta.json. Carries no 'verified' flag (§3)."""
        return {
            "total_dollars": round(self.total_dollars, 6),
            "run_count": self.run_count,
            "failed_count": self.failed_count,
        }


# --------------------------------------------------------------------------- #
# Default client factory (lazy exa-py import)
# --------------------------------------------------------------------------- #
def _default_client_factory() -> Any:
    """Build a real exa-py client from EXA_API_KEY. Imported lazily."""
    api_key = os.environ.get("EXA_API_KEY")
    if not api_key:
        raise MissingApiKeyError()
    try:
        from exa_py import Exa  # noqa: PLC0415 — lazy so tests run without it
    except ImportError as exc:  # pragma: no cover - exercised only without exa-py
        raise ExaAgentError(
            "exa-py is not installed. Install it with `uv add exa-py` (or "
            "`pip install exa-py`) to use the default Exa Agent client."
        ) from exc
    return Exa(api_key=api_key)


def _is_rate_limit(exc: Exception) -> bool:
    if getattr(exc, "status_code", None) == 429:
        return True
    text = str(exc).lower()
    return "429" in text or "rate limit" in text or "too many requests" in text


# --------------------------------------------------------------------------- #
# The client
# --------------------------------------------------------------------------- #
class ExaAgentClient:
    """Shared Exa Agent client.

    Either inject a built exa-py-style client (``client=``) — the unit-test
    path, offline — or pass a ``client_factory`` (defaults to the real exa-py
    builder, which reads EXA_API_KEY).
    """

    def __init__(
        self,
        client: Any | None = None,
        client_factory: Callable[[], Any] | None = None,
        accountant: CostAccountant | None = None,
        read_retries: int = _DEFAULT_READ_RETRIES,
        write_retries: int = _DEFAULT_WRITE_RETRIES,
        breaker_threshold: int = _DEFAULT_BREAKER_THRESHOLD,
        poll_interval_ms: int = _DEFAULT_POLL_INTERVAL_MS,
        timeout_s: int = _DEFAULT_TIMEOUT_S,
    ) -> None:
        if client is not None:
            self._client = client
        else:
            factory = client_factory or _default_client_factory
            self._client = factory()

        self.accountant = accountant
        self.read_retries = read_retries
        self.write_retries = write_retries
        self.breaker_threshold = breaker_threshold
        self.poll_interval_ms = poll_interval_ms
        self.timeout_s = timeout_s

        self._consecutive_failures = 0

    # -- public research jobs ------------------------------------------------ #
    def run_recon(
        self,
        company: str,
        role: str,
        url: str,
        effort: str = "medium",
        enrich_contacts: bool = False,
    ) -> tuple[ReconResult, Any, dict[str, Any]]:
        """Run the recon-3 job: contact + company-context for one role.

        Returns ``(validated ReconResult, grounding trace, cost dict)``.
        ``effort`` defaults to ``medium`` (flat, predictable cost; §5).
        """
        query = (
            f"Find the hiring manager / decision maker and company context for the "
            f"role '{role}' at {company} ({url}). Return the primary contact, "
            f"alternative contacts, and a short company context."
        )
        if enrich_contacts:
            query += " Enrich contacts with email and LinkedIn where available."
        schema = json_schema(ReconResult)
        return self._run(
            query=query,
            output_schema=schema,
            effort=effort,
            model=ReconResult,
        )

    def run_discover(
        self,
        icp: str,
        max_items: int,
        effort: str = "auto",
        exclusions: list[dict[str, Any]] | None = None,
    ) -> tuple[DiscoverResult, Any, dict[str, Any]]:
        """Run the discoverer-6 job: build an ICP-fit company list.

        ``effort`` defaults to ``auto`` and the list is bounded by ``max_items``
        (a ``maxItems`` cap baked into the output schema; §5 predictable cost).
        """
        query = (
            f"Find up to {max_items} companies matching this ICP: {icp}. For each, "
            f"return name, domain, ATS, careers URL, and an ICP-fit score with "
            f"reasoning."
        )
        schema = json_schema(DiscoverResult)
        schema["properties"]["companies"]["maxItems"] = max_items
        extra: dict[str, Any] = {}
        if exclusions:
            extra["input"] = {"exclusion": exclusions}
        return self._run(
            query=query,
            output_schema=schema,
            effort=effort,
            model=DiscoverResult,
            **extra,
        )

    def fetch_contents(self, url: str, **kwargs: Any) -> Any:
        """Thin Exa Search-API contents helper for scout-1's single-page fetch.

        Stays on the Search API (``get_contents``) — paying an Agent ACU run for
        one fetch violates ``$/successful-task`` (§5 non-goal). Injectable.
        """
        return self._client.get_contents([url], **kwargs)

    # -- internals ----------------------------------------------------------- #
    def _run(
        self,
        query: str,
        output_schema: dict[str, Any],
        effort: str,
        model: type,
        **create_kwargs: Any,
    ) -> tuple[Any, Any, dict[str, Any]]:
        """Create → poll → validate, with caps, retries, and meter-on-failure."""
        if self.accountant is not None:
            self.accountant.precheck()

        self._check_breaker()

        # Write step (create the run) — low retry ceiling, fail loudly.
        run = self._with_retries(
            lambda: self._client.agent.runs.create(
                query=query,
                output_schema=output_schema,
                effort=effort,
                **create_kwargs,
            ),
            self.write_retries,
        )

        # Read step (poll to terminal) — higher retry ceiling. run.id is the
        # idempotency key: a retried poll resumes the same run, never a new one.
        run_id = getattr(run, "id", None)
        finished = self._with_retries(
            lambda: self._client.agent.runs.poll_until_finished(
                run_id, poll_interval=self.poll_interval_ms
            ),
            self.read_retries,
        )

        cost = self._extract_cost(finished, run_id)
        status = getattr(finished, "status", None)
        structured = self._structured(finished)
        succeeded = status == "completed" and structured is not None

        # Meter every run — failed/empty included (§5).
        if self.accountant is not None:
            self.accountant.charge(
                run_id=cost["run_id"],
                dollars=cost["dollars"],
                made_progress=succeeded,
                succeeded=succeeded,
            )

        if not succeeded:
            raise RuntimeError(
                f"Exa Agent run {cost['run_id']} did not complete successfully "
                f"(status={status!r}, structured={'present' if structured else 'empty'}). "
                f"Metered ${cost['dollars']:.4f}."
            )

        result = model.model_validate(structured)
        grounding = self._grounding(finished)
        return result, grounding, cost

    def _with_retries(self, call: Callable[[], Any], retries: int) -> Any:
        """Run ``call`` with a bounded retry ceiling. Fails loudly at the cap.

        Rate-limit / concurrency refusals are mapped to a typed prompt error and
        NOT retried (retrying a concurrency cap just burns the cap). A trip of
        the breaker on the final failure surfaces on the next call.
        """
        attempt = 0
        while True:
            try:
                out = self._call_with_timeout(call)
                self._consecutive_failures = 0
                return out
            except Exception as exc:
                if _is_rate_limit(exc):
                    self._record_failure()
                    raise RateLimitError() from exc
                attempt += 1
                if attempt > retries:
                    self._record_failure()
                    raise
                # else: retry (per-attempt timeout/transient error)

    def _call_with_timeout(self, call: Callable[[], Any]) -> Any:
        """Run one attempt under a wall-clock deadline of ``self.timeout_s``.

        A timed-out attempt is abandoned (the worker thread is not awaited:
        ``shutdown(wait=False)``) and raised as a typed ``ExaTimeoutError`` so the
        retry loop treats it like any other failed attempt. ``timeout_s <= 0`` (or
        ``None``) disables the deadline and calls directly.
        """
        if not self.timeout_s or self.timeout_s <= 0:
            return call()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(call)
        try:
            try:
                return future.result(timeout=self.timeout_s)
            except concurrent.futures.TimeoutError as exc:
                # Disambiguate the deadline timeout from a worker that itself
                # raised TimeoutError (in 3.11+ both are the same class): only an
                # unfinished future is a real per-attempt timeout.
                if not future.done():
                    raise ExaTimeoutError(self.timeout_s) from exc
                raise
        finally:
            executor.shutdown(wait=False)

    def _record_failure(self) -> None:
        self._consecutive_failures += 1

    def _check_breaker(self) -> None:
        if self._consecutive_failures >= self.breaker_threshold:
            raise CircuitBreakerOpen()

    # -- response parsing ---------------------------------------------------- #
    @staticmethod
    def _structured(run: Any) -> Any:
        output = getattr(run, "output", None)
        if output is None:
            return None
        return getattr(output, "structured", None)

    @staticmethod
    def _grounding(run: Any) -> Any:
        output = getattr(run, "output", None)
        if output is None:
            return None
        return getattr(output, "grounding", None)

    @staticmethod
    def _extract_cost(run: Any, fallback_id: str | None) -> dict[str, Any]:
        """Parse costDollars + ACU + searches + contacts into a meta.json dict.

        Carries no 'verified' flag (§3): cost is a meter, not a verifier.
        """
        run_id = getattr(run, "id", None) or fallback_id

        cost_dollars = getattr(run, "costDollars", None)
        if isinstance(cost_dollars, dict):
            dollars = float(cost_dollars.get("total", 0.0) or 0.0)
        elif cost_dollars is not None:
            dollars = float(cost_dollars)
        else:
            dollars = 0.0

        usage = getattr(run, "usage", None) or {}
        if not isinstance(usage, dict):
            usage = {
                "agentComputeUnits": getattr(usage, "agentComputeUnits", None),
                "searches": getattr(usage, "searches", None),
                "contacts": getattr(usage, "contacts", None),
            }

        return {
            "run_id": run_id,
            "dollars": dollars,
            "acu": usage.get("agentComputeUnits"),
            "searches": usage.get("searches"),
            "contacts": usage.get("contacts"),
        }
