"""Unit tests for the dossier-research CLI (spec §2).

The CLI is the thin Bash-reachable face over ``ExaAgentClient``. These tests
drive it with Click's ``CliRunner`` and a mocked client so no real ``exa-py``
or network is touched. Every test maps to a spec §2 requirement:

- ``recon`` / ``discover`` happy paths call the client and emit structured JSON
- the emitted JSON carries result + grounding trace + cost, and is size-capped
- the CLI does NOT render markdown, does NOT verify, and does NOT write
  portals.yml / validate URLs (the agent does those)
- typed client exceptions render as friendly, actionable prompt messages
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from board_aggregator import exa_cli
from board_aggregator.exa_agent import (
    CircuitBreakerOpen,
    CostCapExceeded,
    MissingApiKeyError,
    NoProgressError,
    RateLimitError,
)
from board_aggregator.exa_schemas import Company, Contact, DiscoverResult, ReconResult


# --------------------------------------------------------------------------- #
# Fakes / fixtures
# --------------------------------------------------------------------------- #
def _recon_result():
    return ReconResult(
        primary_contact=Contact(
            name="Jane Doe", title="Head of Engineering", email="jane@acme.com"
        ),
        alternative_contacts=[Contact(name="John Roe", title="Recruiter")],
        company_context="Series B, AI infra.",
    )


def _discover_result():
    return DiscoverResult(
        companies=[
            Company(name="Acme", domain="acme.com", ats="greenhouse",
                    careers_url="https://acme.com/careers", icp_fit_score=0.9),
            Company(name="Globex", ats="ashby"),
        ]
    )


def _grounding():
    return [{"field": "primary_contact.email", "url": "https://acme.com/team"}]


def _cost():
    return {"run_id": "agent_run_1", "dollars": 0.10, "acu": 1.0,
            "searches": 3, "contacts": {"emails": 1, "phones": 0}}


class FakeClient:
    """Records the call and returns a canned (result, grounding, cost) triple."""

    def __init__(self, recon=None, discover=None, raises=None):
        self._recon = recon
        self._discover = discover
        self._raises = raises
        self.recon_calls = []
        self.discover_calls = []

    def run_recon(self, **kwargs):
        self.recon_calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return self._recon

    def run_discover(self, **kwargs):
        self.discover_calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return self._discover


@pytest.fixture
def patch_client(monkeypatch):
    """Patch the CLI's client builder to return a supplied fake."""

    def _install(fake):
        monkeypatch.setattr(exa_cli, "_build_client", lambda **_: fake)
        return fake

    return _install


# --------------------------------------------------------------------------- #
# recon happy path
# --------------------------------------------------------------------------- #
def test_recon_happy_path_emits_json(patch_client):
    fake = patch_client(FakeClient(recon=(_recon_result(), _grounding(), _cost())))
    runner = CliRunner()
    res = runner.invoke(
        exa_cli.main,
        ["recon", "--company", "Acme", "--role", "AI Engineer",
         "--url", "https://acme.com/jobs/1"],
    )
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    # result + grounding trace + cost are all present.
    assert payload["result"]["primary_contact"]["name"] == "Jane Doe"
    assert payload["grounding"] == _grounding()
    assert payload["cost"]["dollars"] == pytest.approx(0.10)


def test_recon_forwards_args_to_client(patch_client):
    fake = patch_client(FakeClient(recon=(_recon_result(), _grounding(), _cost())))
    runner = CliRunner()
    res = runner.invoke(
        exa_cli.main,
        ["recon", "--company", "Acme", "--role", "Eng", "--url", "u",
         "--effort", "high", "--enrich"],
    )
    assert res.exit_code == 0, res.output
    call = fake.recon_calls[0]
    assert call["company"] == "Acme"
    assert call["role"] == "Eng"
    assert call["url"] == "u"
    assert call["effort"] == "high"
    assert call["enrich_contacts"] is True


def test_recon_effort_defaults_to_medium(patch_client):
    fake = patch_client(FakeClient(recon=(_recon_result(), _grounding(), _cost())))
    runner = CliRunner()
    res = runner.invoke(
        exa_cli.main, ["recon", "--company", "A", "--role", "r", "--url", "u"]
    )
    assert res.exit_code == 0, res.output
    assert fake.recon_calls[0]["effort"] == "medium"
    assert fake.recon_calls[0]["enrich_contacts"] is False


def test_recon_output_is_pure_json_no_markdown(patch_client):
    # The AGENT renders markdown; the CLI emits only structured JSON.
    patch_client(FakeClient(recon=(_recon_result(), _grounding(), _cost())))
    runner = CliRunner()
    res = runner.invoke(
        exa_cli.main, ["recon", "--company", "A", "--role", "r", "--url", "u"]
    )
    assert res.exit_code == 0, res.output
    # The entire stdout parses as JSON — no markdown headers / prose around it.
    json.loads(res.output)
    assert "#" not in res.output


def test_recon_json_is_size_capped(patch_client):
    # An over-long company_context must be truncated so the structured return
    # stays a capped prompt, not an unbounded dump (§2 "size-capped").
    big = _recon_result()
    big.company_context = "x" * 100_000
    patch_client(FakeClient(recon=(big, _grounding(), _cost())))
    runner = CliRunner()
    res = runner.invoke(
        exa_cli.main, ["recon", "--company", "A", "--role", "r", "--url", "u"]
    )
    assert res.exit_code == 0, res.output
    assert len(res.output) < 50_000


# --------------------------------------------------------------------------- #
# discover happy path
# --------------------------------------------------------------------------- #
def test_discover_happy_path_emits_companies_json(patch_client):
    fake = patch_client(
        FakeClient(discover=(_discover_result(), None, _cost()))
    )
    runner = CliRunner()
    res = runner.invoke(
        exa_cli.main, ["discover", "--icp", "AI infra startups", "--max-items", "5"]
    )
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    names = [c["name"] for c in payload["result"]["companies"]]
    assert names == ["Acme", "Globex"]
    assert payload["cost"]["dollars"] == pytest.approx(0.10)
    call = fake.discover_calls[0]
    assert call["icp"] == "AI infra startups"
    assert call["max_items"] == 5


def test_discover_effort_defaults_to_auto(patch_client):
    fake = patch_client(FakeClient(discover=(_discover_result(), None, _cost())))
    runner = CliRunner()
    res = runner.invoke(exa_cli.main, ["discover", "--icp", "x", "--max-items", "3"])
    assert res.exit_code == 0, res.output
    assert fake.discover_calls[0]["effort"] == "auto"


def test_discover_reads_skills_inventory_file(patch_client, tmp_path):
    # --skills-inventory points at a file; its content folds into the ICP input.
    fake = patch_client(FakeClient(discover=(_discover_result(), None, _cost())))
    inv = tmp_path / "skills-inventory.md"
    inv.write_text("Senior platform engineer, Go + Rust, fintech.")
    runner = CliRunner()
    res = runner.invoke(
        exa_cli.main,
        ["discover", "--skills-inventory", str(inv), "--max-items", "4"],
    )
    assert res.exit_code == 0, res.output
    icp = fake.discover_calls[0]["icp"]
    assert "platform engineer" in icp


def test_discover_requires_icp_or_inventory(patch_client):
    patch_client(FakeClient(discover=(_discover_result(), None, _cost())))
    runner = CliRunner()
    res = runner.invoke(exa_cli.main, ["discover", "--max-items", "4"])
    assert res.exit_code != 0
    assert "icp" in res.output.lower() or "skills-inventory" in res.output.lower()


def test_discover_does_not_write_portals(patch_client, tmp_path, monkeypatch):
    # The CLI must NOT write portals.yml — the agent runs probe-portal (§1, §2).
    monkeypatch.chdir(tmp_path)
    patch_client(FakeClient(discover=(_discover_result(), None, _cost())))
    runner = CliRunner()
    res = runner.invoke(exa_cli.main, ["discover", "--icp", "x", "--max-items", "3"])
    assert res.exit_code == 0, res.output
    assert not (tmp_path / "portals.yml").exists()
    assert list(tmp_path.glob("**/portals.yml")) == []


# --------------------------------------------------------------------------- #
# Errors-as-prompts: typed exceptions render friendly, actionable messages
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "exc, needle",
    [
        (MissingApiKeyError(), "exa_api_key"),
        (RateLimitError(), "concurren"),
        (CostCapExceeded("Max runs reached (1/1)."), "max runs"),
        (NoProgressError("no progress."), "progress"),
        (CircuitBreakerOpen(), "circuit breaker"),
    ],
)
def test_recon_error_rendering(patch_client, exc, needle):
    patch_client(FakeClient(raises=exc))
    runner = CliRunner()
    res = runner.invoke(
        exa_cli.main, ["recon", "--company", "A", "--role", "r", "--url", "u"]
    )
    assert res.exit_code != 0
    # The friendly message reaches the user, not a raw traceback.
    assert "Traceback" not in res.output
    assert needle in res.output.lower()


def test_discover_error_rendering(patch_client):
    patch_client(FakeClient(raises=RateLimitError()))
    runner = CliRunner()
    res = runner.invoke(exa_cli.main, ["discover", "--icp", "x", "--max-items", "3"])
    assert res.exit_code != 0
    assert "Traceback" not in res.output
    assert "concurren" in res.output.lower() or "rate" in res.output.lower()


def test_missing_api_key_renders_without_injected_client(monkeypatch):
    # No injected client and no key: the real builder raises MissingApiKeyError,
    # which must surface as a friendly prompt, not a traceback.
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    runner = CliRunner()
    res = runner.invoke(
        exa_cli.main, ["recon", "--company", "A", "--role", "r", "--url", "u"]
    )
    assert res.exit_code != 0
    assert "Traceback" not in res.output
    assert "exa_api_key" in res.output.lower()


# --------------------------------------------------------------------------- #
# run-dir handling
# --------------------------------------------------------------------------- #
def test_recon_run_dir_is_optional(patch_client):
    patch_client(FakeClient(recon=(_recon_result(), _grounding(), _cost())))
    runner = CliRunner()
    res = runner.invoke(
        exa_cli.main, ["recon", "--company", "A", "--role", "r", "--url", "u"]
    )
    assert res.exit_code == 0, res.output


def test_recon_writes_meta_to_run_dir(patch_client, tmp_path):
    # When --run-dir is given, the cost trace is logged into it as meta material
    # (§5 per-trace instrumentation), and the JSON still goes to stdout.
    patch_client(FakeClient(recon=(_recon_result(), _grounding(), _cost())))
    runner = CliRunner()
    res = runner.invoke(
        exa_cli.main,
        ["recon", "--company", "A", "--role", "r", "--url", "u",
         "--run-dir", str(tmp_path)],
    )
    assert res.exit_code == 0, res.output
    json.loads(res.output)  # stdout is still the JSON payload
    meta = tmp_path / "exa-cost.json"
    assert meta.exists()
    logged = json.loads(meta.read_text())
    assert logged["dollars"] == pytest.approx(0.10)
