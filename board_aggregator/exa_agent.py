"""Shared Exa Agent client for the dossier research agents (spec §2, §3, §5).

One Python client wraps the Exa Agent endpoint (``agent.runs.create`` →
``poll_until_finished``) and is reached the same way by both faces (CLI and the
SaaS sandbox). It holds the two research jobs (``run_recon`` / ``run_discover``),
the Pydantic ``outputSchema`` wiring, reliability primitives (per-attempt
timeout, retry ceiling, circuit breaker, run-ID idempotency), and cost
accounting with the three hard stops.

Design constraints carried from the spec:

- **§3 grounding leads, never verifies.** The client returns an ``ExaRun``
  (``result`` / ``grounding`` / ``cost``). ``grounding`` is a separate audit
  trace; the client NEVER stamps a field ``verified`` — that label is earned
  later by the agent's own full-page fetch. No code path here writes a
  confidence flag.
- **§2 errors are prompts.** Typed exceptions carry recovery text for the
  missing key, the rate-limit / 2-concurrent cap, and a cost-cap hit.
- **§5 meter on failure.** Errored/empty runs are still charged to the
  accountant, or ``$/successful-task`` is unenforceable.

``exa_py`` is lazy-imported only inside the default client factory, so unit
tests run with an injected fake and no real package or network.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import ValidationError

from board_aggregator.exa_schemas import (
    DiscoverResult,
    ReconResult,
    json_schema,
)

# Exa Agent effort tiers, typed at the client boundary. The CLI's click.Choice
# is a separate, narrower surface and stays as-is.
Effort = Literal["minimal", "low", "medium", "high", "xhigh", "auto"]


@dataclass(frozen=True)
class ExaRun:
    """A finished Exa Agent run: the validated answer, its grounding trace, and
    the cost meter — kept as three named, separate fields (§3).

    ``grounding`` is an audit trace that LEADS, never verifies (§3); it is not
    folded into ``result``. ``cost`` stays a plain dict so the optional
    ``estimated`` / ``unknown`` keys and existing ``cost["..."]`` access survive.
    """

    result: "ReconResult | DiscoverResult"
    grounding: Any
    cost: dict[str, Any]

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


class ExaRunFailedError(ExaAgentError):
    """A run reached the boundary non-completed or empty (still metered, §5)."""

    def __init__(self, run_id: str, status: Any, has_structured: bool, dollars: float) -> None:
        super().__init__(
            f"Exa Agent run {run_id} did not complete successfully "
            f"(status={status!r}, structured={'present' if has_structured else 'empty'}). "
            f"Metered ${dollars:.4f}. The run produced no usable result — lower "
            "effort/maxItems, check Exa availability, or retry before relying on output."
        )


class ExaSchemaError(ExaAgentError):
    """The structured output did not match the expected result schema."""

    def __init__(self, run_id: str, detail: str) -> None:
        super().__init__(
            f"Exa Agent run {run_id} returned output that did not match the "
            f"expected schema. The run is unusable as-is — this is a provider/schema "
            f"mismatch, not your input. Retry or report if it persists. Detail: {detail}"
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
        state_path: "str | os.PathLike[str] | None" = None,
    ) -> None:
        self.max_runs = max_runs
        self.per_run_cap = per_run_cap
        self.per_day_cap = per_day_cap
        self.no_progress_limit = no_progress_limit

        self.run_count = 0
        self.failed_count = 0
        self.total_dollars = 0.0
        self._consecutive_no_progress = 0

        # Per-day spend must survive across processes/CLI invocations or the cap
        # resets to $0 every Bash call (finding C2). A date-keyed state file
        # carries today's running total only — counts/dollars, no PII. Missing or
        # corrupt state starts fresh rather than failing closed.
        self._state_path = Path(state_path) if state_path else None
        if self._state_path is not None:
            self.total_dollars = self._load_day_total()

    def _today(self) -> str:
        return date.today().isoformat()

    def _load_day_total(self) -> float:
        """Load today's persisted spend; stale-date / missing / corrupt → 0.0."""
        try:
            data = json.loads(self._state_path.read_text())
        except (OSError, ValueError):
            return 0.0
        if not isinstance(data, dict) or data.get("date") != self._today():
            return 0.0
        try:
            return float(data.get("total_dollars", 0.0))
        except (TypeError, ValueError):
            return 0.0

    def _save_day_total(self) -> None:
        """Persist today's running total. Best-effort: a write failure never
        aborts a run (the in-process caps still hold)."""
        if self._state_path is None:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(
                json.dumps(
                    {"date": self._today(), "total_dollars": round(self.total_dollars, 6)}
                )
            )
        except OSError:
            pass

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

        # Persist the new day total before evaluating the caps so an over-cap
        # run is recorded across invocations (meter-on-failure parity, §5).
        self._save_day_total()

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
        """Cost summary for exa-cost.json (consumed into lead-0's meta.json).

        Carries no 'verified' flag (§3).
        """
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


_RATE_LIMIT_PHRASES = (
    "rate limit",
    "too many requests",
    "quota exceeded",
    "concurren",  # concurrency cap refusals ("concurrency limit reached")
)
# Word-boundary 429 so a status code in a message counts but a "429" buried in a
# URL/path (e.g. /v1/items/429) does not misclassify an unrelated error.
_HTTP_429_RE = re.compile(r"(?<!\d)429(?!\d)")


def _is_rate_limit(exc: Exception) -> bool:
    # Prefer structured signals: an HTTP status_code attribute is unambiguous.
    if getattr(exc, "status_code", None) == 429:
        return True
    # exa-py surfaces rate limits via its own exception type when identifiable.
    if type(exc).__name__ in ("RateLimitError", "RateLimitException"):
        return True
    text = str(exc).lower()
    if any(phrase in text for phrase in _RATE_LIMIT_PHRASES):
        return True
    # Conservative fallback: a word-boundary 429 in the message. A bare "429"
    # inside a longer number or a URL path does not count.
    return bool(_HTTP_429_RE.search(text))


def _jsonable(value: Any) -> Any:
    """Normalize SDK objects into plain JSON-serializable data.

    exa-py returns ``output.grounding`` as SDK objects (``AgentGroundingEntry``),
    which ``json.dumps`` cannot serialize. The client owns the SDK boundary, so
    it converts grounding to plain dicts/lists/scalars before putting it on
    ``ExaRun`` — the CLI and agents must never see raw SDK objects. A live smoke
    run surfaced this; every test fake returned plain dicts and missed it.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    model_dump = getattr(value, "model_dump", None)  # pydantic-based SDK models
    if callable(model_dump):
        try:
            return _jsonable(model_dump(mode="json"))
        except Exception:
            try:
                return _jsonable(model_dump())
            except Exception:
                pass
    data = getattr(value, "__dict__", None)
    if isinstance(data, dict) and data:
        return {
            str(k): _jsonable(v) for k, v in data.items() if not str(k).startswith("_")
        }
    return str(value)


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

        # Sub-call breaker: trips inside the retry loop (per-attempt failures).
        self._consecutive_failures = 0
        # Run-level breaker (finding C2): counts whole `_run` failures and resets
        # ONLY on a full `_run` success. A sub-call success (create-ok / poll-fail)
        # must not reset it, or the create-ok/poll-fail pattern never trips.
        self._consecutive_run_failures = 0

    # -- public research jobs ------------------------------------------------ #
    def run_recon(
        self,
        company: str,
        role: str,
        url: str,
        effort: Effort = "medium",
        enrich_contacts: bool = False,
    ) -> ExaRun:
        """Run the recon-3 job: contact + company-context for one role.

        Returns an ``ExaRun`` (validated ReconResult, grounding trace, cost dict).
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
        effort: Effort = "auto",
        exclusions: list[dict[str, Any]] | None = None,
    ) -> ExaRun:
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
        effort: Effort,
        model: type,
        **create_kwargs: Any,
    ) -> ExaRun:
        """Create → poll → validate, with caps, retries, and meter-on-failure."""
        if self.accountant is not None:
            self.accountant.precheck()

        # Two breakers guard a call. The sub-call breaker (legacy) trips on a
        # storm of per-attempt failures; the run-level breaker (finding C2) trips
        # on N consecutive whole-run failures regardless of which sub-step failed
        # — it is the one that catches the create-ok / poll-fail pattern, which a
        # sub-call success would otherwise keep resetting.
        self._check_breaker()
        self._check_run_breaker()

        try:
            result = self._do_run(query, output_schema, effort, model, **create_kwargs)
        except ExaAgentError:
            # A whole run failed (create/poll/validate). Count it toward the
            # run-level breaker — a sub-call success inside it must not have reset
            # this counter.
            self._consecutive_run_failures += 1
            raise
        else:
            # A full run succeeded end to end: clear the run-level breaker.
            self._consecutive_run_failures = 0
            return result

    def _do_run(
        self,
        query: str,
        output_schema: dict[str, Any],
        effort: Effort,
        model: type,
        **create_kwargs: Any,
    ) -> ExaRun:
        """The create→poll→validate body, wrapped by ``_run`` for the breaker."""
        # Write step (create the run) — low retry ceiling, fail loudly. Read step
        # (poll to terminal) — higher retry ceiling. run.id is the idempotency
        # key: a retried poll resumes the same run, never a new one. Any non-typed
        # error that survives the retry ceiling (e.g. a bare/builtin TimeoutError
        # from a worker) is wrapped into a typed ExaAgentError at the boundary so
        # nothing untyped escapes to the CLI (errors-are-prompts, §2).
        try:
            # A create-step timeout is TERMINAL — never retried. A retried create
            # could spawn a second billable run at Exa whose id we never captured
            # (idempotency only covers the POLL step, which re-polls run.id). One
            # such timeout may leave a single orphaned billable run at Exa: a
            # documented tradeoff, preferred over silently double-billing (I3).
            run = self._with_retries(
                lambda: self._client.agent.runs.create(
                    query=query,
                    output_schema=output_schema,
                    effort=effort,
                    **create_kwargs,
                ),
                self.write_retries,
                terminal_on_timeout=True,
            )

            run_id = getattr(run, "id", None)
            finished = self._with_retries(
                lambda: self._client.agent.runs.poll_until_finished(
                    run_id, poll_interval=self.poll_interval_ms
                ),
                self.read_retries,
            )
        except ExaAgentError:
            raise
        except Exception as exc:
            # _with_retries already recorded the failure at the cap; only wrap
            # the bare/builtin error into a typed one (do not double-count).
            raise ExaAgentError(
                "The Exa Agent call failed with an unexpected error after the "
                f"retry ceiling: {type(exc).__name__}: {exc}. Check Exa "
                "availability / credentials before retrying."
            ) from exc

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
            raise ExaRunFailedError(
                run_id=cost["run_id"],
                status=status,
                has_structured=structured is not None,
                dollars=cost["dollars"],
            )

        try:
            result = model.model_validate(structured)
        except ValidationError as exc:
            raise ExaSchemaError(cost["run_id"], str(exc)) from exc
        grounding = self._grounding(finished)
        return ExaRun(result=result, grounding=grounding, cost=cost)

    def _with_retries(
        self,
        call: Callable[[], Any],
        retries: int,
        terminal_on_timeout: bool = False,
    ) -> Any:
        """Run ``call`` with a bounded retry ceiling. Fails loudly at the cap.

        Rate-limit / concurrency refusals are mapped to a typed prompt error and
        NOT retried (retrying a concurrency cap just burns the cap). A trip of
        the breaker on the final failure surfaces on the next call.

        ``terminal_on_timeout`` (the create step) makes an ``ExaTimeoutError``
        non-retryable: retrying a create could spawn a duplicate billable run
        (I3). Poll-step timeouts are safe to retry — they re-poll the same run id.
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
                if terminal_on_timeout and isinstance(exc, ExaTimeoutError):
                    self._record_failure()
                    raise
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

    def _check_run_breaker(self) -> None:
        if self._consecutive_run_failures >= self.breaker_threshold:
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
        """Grounding trace as plain JSON-able data (§3 audit trace).

        exa-py returns these as SDK objects (``AgentGroundingEntry``); normalize
        at the boundary via ``_jsonable`` so ``ExaRun.grounding`` is always
        serializable by the CLI/agent.
        """
        output = getattr(run, "output", None)
        if output is None:
            return None
        return _jsonable(getattr(output, "grounding", None))

    def _extract_cost(self, run: Any, fallback_id: str | None) -> dict[str, Any]:
        """Parse costDollars + ACU + searches + contacts into the exa-cost.json
        dict (consumed into lead-0's meta.json).

        Cost must never under-report a billed run (§5): a real spend metered as
        $0 caps compute against zero. Three distinct shapes are handled:

        - ``costDollars`` present and parseable → use it verbatim.
        - ``costDollars`` absent/None but usage present → estimate from the
          component breakdown (1 ACU = $0.10, $0.005/search, $0.02/email,
          $0.07/phone) and flag ``estimated``.
        - ``costDollars`` present but unparseable → do NOT silently coerce to 0;
          fail closed by metering at the per-run cap and flag ``unknown`` so the
          caps stay enforceable rather than billing a free pass.

        Carries no 'verified' flag (§3): cost is a meter, not a verifier.
        """
        run_id = getattr(run, "id", None) or fallback_id

        usage = getattr(run, "usage", None) or {}
        if not isinstance(usage, dict):
            usage = {
                "agentComputeUnits": getattr(usage, "agentComputeUnits", None),
                "searches": getattr(usage, "searches", None),
                "contacts": getattr(usage, "contacts", None),
            }

        cost: dict[str, Any] = {
            "run_id": run_id,
            "acu": usage.get("agentComputeUnits"),
            "searches": usage.get("searches"),
            "contacts": usage.get("contacts"),
        }

        cost_dollars = getattr(run, "costDollars", None)
        raw = cost_dollars.get("total") if isinstance(cost_dollars, dict) else cost_dollars

        if raw is None:
            # No billed total reported: estimate from components rather than $0.
            cost["dollars"] = self._estimate_dollars(usage)
            cost["estimated"] = True
        else:
            try:
                cost["dollars"] = float(raw)
            except (TypeError, ValueError):
                # Present but unparseable: fail closed at the per-run cap.
                cost["dollars"] = self._per_run_cap()
                cost["unknown"] = True

        return cost

    def _per_run_cap(self) -> float:
        """The per-run dollar ceiling used as the fail-closed cost on unknowns."""
        if self.accountant is not None:
            return self.accountant.per_run_cap
        return CostAccountant().per_run_cap

    @staticmethod
    def _estimate_dollars(usage: dict[str, Any]) -> float:
        """Component-math fallback: 1 ACU=$0.10, $0.005/search, $0.02/email,
        $0.07/phone. Missing/unparseable components count as zero.
        """

        def _num(value: Any) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0

        contacts = usage.get("contacts") or {}
        if not isinstance(contacts, dict):
            contacts = {}
        return (
            _num(usage.get("agentComputeUnits")) * 0.10
            + _num(usage.get("searches")) * 0.005
            + _num(contacts.get("emails")) * 0.02
            + _num(contacts.get("phones")) * 0.07
        )
