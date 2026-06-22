"""Static contract tests for the Exa-Agent swap (spec U5, §1/§4/§5).

These guard the agent-prompt swap: the research agents move off the
``mcp__exa__*`` Search-API MCP tools onto the shared ``dossier-research`` CLI
(recon-3 / discoverer-6) or the Exa Search-API contents path (scout-1), with
quarantine tightened (no raw Exa content into lead-0) and per-run Exa cost
logged into ``meta.json`` (§5).

The fix for an agent-prompt swap is unambiguous prompt text; these are
grep-able assertions over that text and the YAML frontmatter ``tools:`` lists.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS = REPO_ROOT / ".claude" / "agents"

RECON_3 = AGENTS / "recon-3.md"
DISCOVERER_6 = AGENTS / "discoverer-6.md"
SCOUT_1 = AGENTS / "scout-1.md"
PRIMER_8 = AGENTS / "primer-8.md"
LEAD_0 = AGENTS / "lead-0.md"

ALL_AGENTS = [RECON_3, DISCOVERER_6, SCOUT_1, PRIMER_8, LEAD_0]


def _read(path: Path) -> str:
    return path.read_text()


def _frontmatter(path: Path) -> str:
    """Return the YAML frontmatter block (between the first two ``---`` fences)."""
    return _read(path).split("---", 2)[1]


# --- §1: no agent prompt references the retired Search-API MCP tools ---

def test_no_agent_references_exa_mcp():
    for path in ALL_AGENTS:
        assert "mcp__exa__" not in _read(path), (
            f"{path.name} still references a retired mcp__exa__* tool"
        )


# --- §1: research agents reach the real dossier-research CLI command ---

def test_recon_3_calls_dossier_research_recon():
    text = _read(RECON_3)
    assert "dossier-research recon" in text
    # Reached via scoped Bash, not a fabricated tool.
    assert "Bash" in _frontmatter(RECON_3)


def test_discoverer_6_calls_dossier_research_discover():
    text = _read(DISCOVERER_6)
    assert "dossier-research discover" in text
    assert "Bash" in _frontmatter(DISCOVERER_6)


# --- §1 capability widening: recon-3 gains Bash, instructed to use it
#     only for dossier-research + fetch tools (behavioral, not a false
#     harness-enforcement claim — finding I2) ---

def test_recon_3_bash_instructed_to_dossier_research_only():
    text = _read(RECON_3)
    front = _frontmatter(RECON_3)
    assert "Bash" in front
    # recon-3 must be *instructed* to keep Bash to dossier-research only.
    assert "dossier-research" in text
    # Truthfulness: it must NOT claim the harness/settings enforce a
    # per-agent Bash scope — there is no such scoping (finding I2).
    lower = text.lower()
    assert "settings allowlist" not in lower, (
        "recon-3 must not claim a settings-allowlist Bash scope that "
        "does not exist (finding I2)"
    )
    assert "scoped to" not in lower, (
        "recon-3 must not claim its Bash is harness-scoped (finding I2)"
    )


# --- §3: recon-3 retains its OWN-fetch verification capability ---

def test_recon_3_retains_own_fetch_tool():
    """The own-fetch verifier (WebFetch) must survive the search-side swap (§3)."""
    front = _frontmatter(RECON_3)
    assert "WebFetch" in front
    assert "Read" in front
    assert "Write" in front


# --- §4 quarantine: research agents stay read-only (no send/submit tools) ---

def test_recon_3_has_no_send_tools():
    front = _frontmatter(RECON_3)
    for forbidden in ["Gmail", "create_draft", "filler", "applier", "submit"]:
        assert forbidden not in front, f"recon-3 must not gain a send tool: {forbidden}"


def test_discoverer_6_has_no_send_tools():
    front = _frontmatter(DISCOVERER_6)
    for forbidden in ["Gmail", "create_draft", "filler", "applier", "submit"]:
        assert forbidden not in front, f"discoverer-6 must not gain a send tool: {forbidden}"


# --- §1: discoverer-6 keeps the code-side probe-portal ATS validation + gate ---

def test_discoverer_6_keeps_probe_portal_gate():
    text = _read(DISCOVERER_6)
    lower = text.lower()
    assert "probe-portal" in text
    assert "setup_wizard.py probe-portal" in text
    # The WRITE/DROP/SKIP verdict gate must survive the swap.
    assert "write" in lower and "drop" in lower and "skip" in lower
    assert "icp_min_score" in text


# --- §1: scout-1 moves off web_fetch_exa onto the Search-API contents path ---

def test_scout_1_uses_search_api_contents_path():
    text = _read(SCOUT_1)
    front = _frontmatter(SCOUT_1)
    # The MCP fetch tool is gone from the tool list.
    assert "mcp__exa__web_fetch_exa" not in front
    assert "mcp__exa__" not in front
    # And it reaches the Search-API contents path (fetch_contents / board aggregator).
    lower = text.lower()
    assert "fetch_contents" in lower or "dossier-research" in lower or "get_contents" in lower


# --- §6: primer-8 configures EXA_API_KEY env var, not the Exa MCP ---

def test_primer_8_configures_exa_api_key_env_var():
    text = _read(PRIMER_8)
    assert "EXA_API_KEY" in text
    # The readiness/onboarding language must reference the env var, not `claude mcp add ... exa`.
    assert "claude mcp add" not in text or "exa" not in text.lower().split("claude mcp add")[1][:200]


# --- §4 quarantine + §5 cost: lead-0 gets only distilled summaries, logs cost ---

def test_lead_0_no_raw_exa_content_in_context():
    lower = _read(LEAD_0).lower()
    # lead-0 must not gain raw web content; quarantine language present.
    assert "distilled" in lower or "summaries only" in lower or "summary" in lower
    # lead-0 still must not hold any mcp__exa__* tool.
    assert "mcp__exa__" not in _read(LEAD_0)


def test_lead_0_logs_exa_cost_into_meta_json():
    text = _read(LEAD_0)
    lower = text.lower()
    assert "meta.json" in lower
    # §5: cost fields logged per run.
    assert "costdollars" in lower or "costDollars" in text
    assert "acu" in lower
    assert "searches" in lower
    assert "contacts" in lower
