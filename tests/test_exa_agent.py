"""Unit tests for the shared Exa Agent client (spec §2, §3, §5).

The client is tested entirely against a ``FakeExaClient`` — no real ``exa-py``
package and no network. Every test below maps to a spec requirement:

- run lifecycle (create → poll_until_finished → validated result)
- schema validation of the structured output
- cost extraction (costDollars + ACU + searches + contacts)
- the three hard stops (max runs, no-progress, dollar ceiling) abort
- meter-on-failure (errored/empty runs are still metered)
- missing EXA_API_KEY raises a typed, prompt-shaped error
- retry ceiling (3 for reads) and write-step fail-loud
- the client never labels a field 'verified' (§3 grounding-is-a-lead)
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from board_aggregator.exa_agent import (
    CircuitBreakerOpen,
    CostAccountant,
    CostCapExceeded,
    ExaAgentClient,
    ExaTimeoutError,
    MissingApiKeyError,
    NoProgressError,
    RateLimitError,
)
from board_aggregator.exa_schemas import DiscoverResult, ReconResult


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeRun:
    """Minimal stand-in for an exa-py agent run object."""

    def __init__(self, id, status, structured=None, grounding=None,
                 text=None, cost_dollars=None, usage=None):
        self.id = id
        self.status = status
        self.output = _FakeOutput(structured, grounding, text)
        self.costDollars = cost_dollars
        self.usage = usage


class _FakeOutput:
    def __init__(self, structured, grounding, text):
        self.structured = structured
        self.grounding = grounding
        self.text = text


class FakeRuns:
    def __init__(self, parent):
        self._parent = parent

    def create(self, **kwargs):
        self._parent.create_calls.append(kwargs)
        return self._parent._next_create()

    def poll_until_finished(self, run_id, **kwargs):
        self._parent.poll_calls.append((run_id, kwargs))
        return self._parent._next_poll(run_id)


class FakeAgent:
    def __init__(self, parent):
        self.runs = FakeRuns(parent)


class FakeExaClient:
    """Injectable fake mimicking the exa-py surface the client uses.

    Configure ``create_runs`` (returned by create, in order) and ``poll_runs``
    (returned by poll_until_finished, keyed by run id or popped in order).
    """

    def __init__(self, create_runs=None, poll_runs=None):
        self._create_runs = list(create_runs or [])
        self._poll_runs = list(poll_runs or [])
        self.create_calls = []
        self.poll_calls = []
        self.agent = FakeAgent(self)

    def _next_create(self):
        if not self._create_runs:
            raise AssertionError("FakeExaClient.create called more than expected")
        return self._create_runs.pop(0)

    def _next_poll(self, run_id):
        if not self._poll_runs:
            raise AssertionError("FakeExaClient.poll called more than expected")
        return self._poll_runs.pop(0)


def _recon_structured():
    return {
        "primary_contact": {
            "name": "Jane Doe",
            "title": "Head of Engineering",
            "email": "jane@acme.com",
        },
        "alternative_contacts": [{"name": "John Roe", "title": "Recruiter"}],
        "company_context": "Series B, AI infra.",
    }


def _completed_recon_run(run_id="agent_run_1"):
    return FakeRun(
        id=run_id,
        status="completed",
        structured=_recon_structured(),
        grounding=[{"field": "primary_contact.email", "url": "https://acme.com/team"}],
        text="Found Jane Doe.",
        cost_dollars={"total": 0.10},
        usage={"agentComputeUnits": 1.0, "searches": 3, "contacts": {"emails": 1, "phones": 0}},
    )


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #
def test_run_recon_lifecycle_returns_result_grounding_cost():
    fake = FakeExaClient(
        create_runs=[FakeRun("agent_run_1", "queued")],
        poll_runs=[_completed_recon_run("agent_run_1")],
    )
    client = ExaAgentClient(client=fake)
    result, grounding, cost = client.run_recon(
        company="Acme", role="AI Engineer", url="https://acme.com/jobs/1"
    )
    assert isinstance(result, ReconResult)
    assert result.primary_contact.name == "Jane Doe"
    # grounding is surfaced as a separate trace, not folded into the answer.
    assert grounding == [{"field": "primary_contact.email", "url": "https://acme.com/team"}]
    assert cost["dollars"] == pytest.approx(0.10)
    # create then poll, in that order.
    assert len(fake.create_calls) == 1
    assert fake.poll_calls[0][0] == "agent_run_1"


def test_run_recon_passes_output_schema_and_effort():
    fake = FakeExaClient(
        create_runs=[FakeRun("r", "queued")],
        poll_runs=[_completed_recon_run("r")],
    )
    client = ExaAgentClient(client=fake)
    client.run_recon(company="Acme", role="Eng", url="u", effort="medium")
    kwargs = fake.create_calls[0]
    assert kwargs["effort"] == "medium"
    schema = kwargs["output_schema"]
    assert schema["type"] == "object"
    assert "primary_contact" in schema["properties"]


def test_run_discover_lifecycle():
    structured = {"companies": [{"name": "Acme", "ats": "greenhouse"}]}
    fake = FakeExaClient(
        create_runs=[FakeRun("d1", "queued")],
        poll_runs=[FakeRun("d1", "completed", structured=structured,
                           cost_dollars={"total": 0.25},
                           usage={"agentComputeUnits": 2.5, "searches": 5})],
    )
    client = ExaAgentClient(client=fake)
    result, grounding, cost = client.run_discover(icp="AI infra startups", max_items=10)
    assert isinstance(result, DiscoverResult)
    assert result.companies[0].name == "Acme"
    kwargs = fake.create_calls[0]
    assert kwargs["effort"] == "auto"
    # maxItems bound flows into the output schema.
    assert kwargs["output_schema"]["properties"]["companies"]["maxItems"] == 10


def test_run_discover_passes_exclusions():
    fake = FakeExaClient(
        create_runs=[FakeRun("d", "queued")],
        poll_runs=[FakeRun("d", "completed", structured={"companies": []},
                           cost_dollars={"total": 0.0}, usage={})],
    )
    client = ExaAgentClient(client=fake)
    client.run_discover(icp="x", max_items=5, exclusions=[{"name": "Acme"}])
    kwargs = fake.create_calls[0]
    assert kwargs["input"]["exclusion"] == [{"name": "Acme"}]


# --------------------------------------------------------------------------- #
# Schema validation
# --------------------------------------------------------------------------- #
def test_invalid_structured_output_raises_validation_error():
    # primary_contact is required by ReconResult; a structured payload missing it
    # must fail validation rather than return a half-built object.
    fake = FakeExaClient(
        create_runs=[FakeRun("r", "queued")],
        poll_runs=[FakeRun("r", "completed", structured={"company_context": "no contact"},
                           cost_dollars={"total": 0.10}, usage={})],
    )
    client = ExaAgentClient(client=fake)
    with pytest.raises(ValidationError):
        client.run_recon(company="Acme", role="Eng", url="u")


# --------------------------------------------------------------------------- #
# Cost extraction (§5)
# --------------------------------------------------------------------------- #
def test_cost_extraction_parses_all_components():
    run = _completed_recon_run("r")
    fake = FakeExaClient(create_runs=[FakeRun("r", "queued")], poll_runs=[run])
    client = ExaAgentClient(client=fake)
    _, _, cost = client.run_recon(company="Acme", role="Eng", url="u")
    assert cost["dollars"] == pytest.approx(0.10)
    assert cost["acu"] == pytest.approx(1.0)
    assert cost["searches"] == 3
    assert cost["contacts"] == {"emails": 1, "phones": 0}
    assert cost["run_id"] == "r"


def test_cost_dict_for_meta_json_is_serializable():
    import json

    run = _completed_recon_run("r")
    fake = FakeExaClient(create_runs=[FakeRun("r", "queued")], poll_runs=[run])
    client = ExaAgentClient(client=fake)
    _, _, cost = client.run_recon(company="Acme", role="Eng", url="u")
    json.dumps(cost)  # must not raise


# --------------------------------------------------------------------------- #
# §3 constraint: client never labels a field verified
# --------------------------------------------------------------------------- #
def test_client_never_emits_verified_label():
    run = _completed_recon_run("r")
    fake = FakeExaClient(create_runs=[FakeRun("r", "queued")], poll_runs=[run])
    client = ExaAgentClient(client=fake)
    result, grounding, cost = client.run_recon(company="Acme", role="Eng", url="u")
    # The returned data + grounding + cost carry no 'verified' flag anywhere.
    assert "verified" not in cost
    assert "confidence" not in result.model_dump()
    assert "verified" not in str(result.model_dump())


# --------------------------------------------------------------------------- #
# CostAccountant — three hard stops + meter-on-failure
# --------------------------------------------------------------------------- #
def test_cost_accountant_max_runs_stop():
    acct = CostAccountant(max_runs=2, per_run_cap=10.0, per_day_cap=100.0)
    acct.charge(run_id="a", dollars=0.1, made_progress=True)
    acct.charge(run_id="b", dollars=0.1, made_progress=True)
    with pytest.raises(CostCapExceeded):
        acct.precheck()


def test_cost_accountant_per_run_cap_aborts():
    acct = CostAccountant(max_runs=10, per_run_cap=0.05, per_day_cap=100.0)
    with pytest.raises(CostCapExceeded):
        acct.charge(run_id="a", dollars=0.10, made_progress=True)
    # the over-cap run is still metered (meter-on-failure).
    assert acct.total_dollars == pytest.approx(0.10)
    assert acct.run_count == 1


def test_cost_accountant_per_day_cap_aborts():
    acct = CostAccountant(max_runs=100, per_run_cap=10.0, per_day_cap=0.15)
    acct.charge(run_id="a", dollars=0.10, made_progress=True)
    with pytest.raises(CostCapExceeded):
        acct.charge(run_id="b", dollars=0.10, made_progress=True)
    assert acct.total_dollars == pytest.approx(0.20)


def test_cost_accountant_no_progress_aborts():
    acct = CostAccountant(max_runs=100, per_run_cap=10.0, per_day_cap=100.0,
                          no_progress_limit=2)
    acct.charge(run_id="a", dollars=0.1, made_progress=False)
    with pytest.raises(NoProgressError):
        acct.charge(run_id="b", dollars=0.1, made_progress=False)
    # progress resets the counter.
    acct2 = CostAccountant(max_runs=100, per_run_cap=10.0, per_day_cap=100.0,
                           no_progress_limit=2)
    acct2.charge(run_id="a", dollars=0.1, made_progress=False)
    acct2.charge(run_id="b", dollars=0.1, made_progress=True)
    acct2.charge(run_id="c", dollars=0.1, made_progress=False)  # no raise


def test_cost_accountant_meters_failed_runs():
    # An errored/empty run still costs money and MUST be metered, or
    # $/successful-task is unenforceable (§5 meter-on-failure).
    acct = CostAccountant(max_runs=100, per_run_cap=10.0, per_day_cap=100.0)
    acct.charge(run_id="a", dollars=0.07, made_progress=False, succeeded=False)
    assert acct.total_dollars == pytest.approx(0.07)
    assert acct.run_count == 1
    assert acct.failed_count == 1


def test_cost_accountant_cost_dict():
    acct = CostAccountant(max_runs=100, per_run_cap=10.0, per_day_cap=100.0)
    acct.charge(run_id="a", dollars=0.10, made_progress=True, succeeded=True)
    acct.charge(run_id="b", dollars=0.05, made_progress=False, succeeded=False)
    d = acct.as_dict()
    assert d["total_dollars"] == pytest.approx(0.15)
    assert d["run_count"] == 2
    assert d["failed_count"] == 1
    import json
    json.dumps(d)


# --------------------------------------------------------------------------- #
# Client wires the accountant: cost-cap raises before/around the run
# --------------------------------------------------------------------------- #
def test_client_aborts_when_cost_cap_hit():
    acct = CostAccountant(max_runs=1, per_run_cap=10.0, per_day_cap=100.0)
    fake = FakeExaClient(
        create_runs=[FakeRun("r1", "queued"), FakeRun("r2", "queued")],
        poll_runs=[_completed_recon_run("r1"), _completed_recon_run("r2")],
    )
    client = ExaAgentClient(client=fake, accountant=acct)
    client.run_recon(company="A", role="r", url="u")  # consumes the 1 allowed run
    with pytest.raises(CostCapExceeded):
        client.run_recon(company="B", role="r", url="u")


def test_client_meters_failed_run_then_raises():
    # A run that finishes 'errored' is metered, then surfaced as a failure.
    acct = CostAccountant(max_runs=10, per_run_cap=10.0, per_day_cap=100.0)
    fake = FakeExaClient(
        create_runs=[FakeRun("r", "queued")],
        poll_runs=[FakeRun("r", "errored", structured=None,
                           cost_dollars={"total": 0.05}, usage={"agentComputeUnits": 0.5})],
    )
    client = ExaAgentClient(client=fake, accountant=acct)
    with pytest.raises(RuntimeError):
        client.run_recon(company="A", role="r", url="u")
    # metered despite failure.
    assert acct.total_dollars == pytest.approx(0.05)
    assert acct.failed_count == 1


# --------------------------------------------------------------------------- #
# Missing key (errors-as-prompts)
# --------------------------------------------------------------------------- #
def test_missing_api_key_raises_typed_error(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    with pytest.raises(MissingApiKeyError) as exc:
        ExaAgentClient()  # default factory needs the key
    msg = str(exc.value).lower()
    assert "exa_api_key" in msg
    # error message is a prompt: it tells the operator how to recover.
    assert "set" in msg or "export" in msg


def test_injected_client_does_not_need_key(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    # Injecting a client bypasses the key read entirely (unit-testable offline).
    fake = FakeExaClient(create_runs=[FakeRun("r", "queued")],
                         poll_runs=[_completed_recon_run("r")])
    client = ExaAgentClient(client=fake)
    result, _, _ = client.run_recon(company="A", role="r", url="u")
    assert isinstance(result, ReconResult)


# --------------------------------------------------------------------------- #
# Retry ceiling + circuit breaker (§2)
# --------------------------------------------------------------------------- #
def test_read_retries_then_succeeds():
    # The read step (poll) honors read_retries: transient timeouts are retried.
    class FlakyRuns(FakeRuns):
        def __init__(self, parent):
            super().__init__(parent)
            self.attempts = 0

        def create(self, **kwargs):
            self._parent.create_calls.append(kwargs)
            return FakeRun("r", "queued")

        def poll_until_finished(self, run_id, **kwargs):
            self.attempts += 1
            if self.attempts < 3:
                raise TimeoutError("transient")
            return _completed_recon_run("r")

    fake = FakeExaClient()
    fake.agent.runs = FlakyRuns(fake)
    client = ExaAgentClient(client=fake, read_retries=3)
    result, _, _ = client.run_recon(company="A", role="r", url="u")
    assert isinstance(result, ReconResult)
    assert fake.agent.runs.attempts == 3


def test_read_retry_ceiling_fails_loudly():
    class AlwaysFails(FakeRuns):
        def __init__(self, parent):
            super().__init__(parent)
            self.attempts = 0

        def create(self, **kwargs):
            return FakeRun("r", "queued")

        def poll_until_finished(self, run_id, **kwargs):
            self.attempts += 1
            raise TimeoutError("transient")

    fake = FakeExaClient()
    fake.agent.runs = AlwaysFails(fake)
    client = ExaAgentClient(client=fake, read_retries=3)
    with pytest.raises(TimeoutError):
        client.run_recon(company="A", role="r", url="u")
    # ceiling honored: initial + 3 retries = 4 poll attempts, no infinite loop.
    assert fake.agent.runs.attempts == 4


def test_circuit_breaker_opens_after_threshold():
    class AlwaysFails(FakeRuns):
        def create(self, **kwargs):
            raise TimeoutError("down")

    fake = FakeExaClient()
    fake.agent.runs = AlwaysFails(fake)
    # 1 retry per call; breaker trips after 2 failed calls.
    client = ExaAgentClient(client=fake, read_retries=1, breaker_threshold=2)
    with pytest.raises(TimeoutError):
        client.run_recon(company="A", role="r", url="u")
    with pytest.raises(TimeoutError):
        client.run_recon(company="A", role="r", url="u")
    # breaker now open: next call short-circuits without touching the client.
    with pytest.raises(CircuitBreakerOpen):
        client.run_recon(company="A", role="r", url="u")


# --------------------------------------------------------------------------- #
# Per-attempt timeout (§2)
# --------------------------------------------------------------------------- #
def test_slow_attempt_raises_typed_timeout_and_is_retried():
    import time

    class SlowRuns(FakeRuns):
        def __init__(self, parent):
            super().__init__(parent)
            self.attempts = 0

        def create(self, **kwargs):
            return FakeRun("r", "queued")

        def poll_until_finished(self, run_id, **kwargs):
            self.attempts += 1
            time.sleep(0.5)  # longer than the 0.05s per-attempt timeout
            return _completed_recon_run("r")

    fake = FakeExaClient()
    fake.agent.runs = SlowRuns(fake)
    client = ExaAgentClient(client=fake, read_retries=2, timeout_s=0.05)
    with pytest.raises(ExaTimeoutError):
        client.run_recon(company="A", role="r", url="u")
    # timeout counts as a failed attempt: initial + 2 retries = 3 poll attempts.
    assert fake.agent.runs.attempts == 3


def test_fast_attempt_passes_under_timeout():
    fake = FakeExaClient(
        create_runs=[FakeRun("agent_run_1", "queued")],
        poll_runs=[_completed_recon_run("agent_run_1")],
    )
    client = ExaAgentClient(client=fake, timeout_s=5.0)
    result, _, _ = client.run_recon(company="A", role="r", url="u")
    assert isinstance(result, ReconResult)


def test_timeout_disabled_does_not_abort_slow_call():
    import time

    class SlowOnceRuns(FakeRuns):
        def create(self, **kwargs):
            return FakeRun("r", "queued")

        def poll_until_finished(self, run_id, **kwargs):
            time.sleep(0.1)  # would trip a small timeout, but it's disabled
            return _completed_recon_run("r")

    fake = FakeExaClient()
    fake.agent.runs = SlowOnceRuns(fake)
    client = ExaAgentClient(client=fake, timeout_s=0)
    result, _, _ = client.run_recon(company="A", role="r", url="u")
    assert isinstance(result, ReconResult)


# --------------------------------------------------------------------------- #
# Rate-limit / concurrency error (errors-as-prompts)
# --------------------------------------------------------------------------- #
def test_rate_limit_maps_to_typed_prompt_error():
    class RateLimited(FakeRuns):
        def create(self, **kwargs):
            raise _FakeHttp429("429 Too Many Requests")

    fake = FakeExaClient()
    fake.agent.runs = RateLimited(fake)
    client = ExaAgentClient(client=fake, read_retries=0)
    with pytest.raises(RateLimitError) as exc:
        client.run_recon(company="A", role="r", url="u")
    msg = str(exc.value).lower()
    assert "concurren" in msg or "rate" in msg
    assert "2" in msg  # mentions the 2-concurrent-at-default-QPS cap


class _FakeHttp429(Exception):
    status_code = 429


# --------------------------------------------------------------------------- #
# fetch_contents (scout-1 Search-API helper)
# --------------------------------------------------------------------------- #
def test_fetch_contents_uses_injected_client():
    class ContentsClient:
        def __init__(self):
            self.calls = []

        def get_contents(self, urls, **kwargs):
            self.calls.append((urls, kwargs))
            return {"results": [{"url": urls[0], "text": "page body"}]}

    cc = ContentsClient()
    client = ExaAgentClient(client=cc)
    out = client.fetch_contents("https://acme.com/jobs/1")
    assert out["results"][0]["text"] == "page body"
    assert cc.calls[0][0] == ["https://acme.com/jobs/1"]
