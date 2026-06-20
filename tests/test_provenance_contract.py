"""Static contract tests for the anti-fabrication / provenance rules.

These guard the agent-prompt contract that other agents cite. They assert the
load-bearing rule text is present (and not silently weakened) in the project
CLAUDE.md and the recon-3 agent definition. See first-user-session findings
T1-7 (anti-fabrication too narrow), T1-3 (overconfident contact attribution),
and T4-4 (subagents leak internal tool architecture).
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MD = REPO_ROOT / ".claude" / "CLAUDE.md"
RECON_3 = REPO_ROOT / ".claude" / "agents" / "recon-3.md"


def _claude_md() -> str:
    return CLAUDE_MD.read_text()


def _recon_3() -> str:
    return RECON_3.read_text()


# --- T1-7: anti-fabrication covers research provenance, not just pitch material ---

def test_claude_md_forbids_unfetched_research_provenance():
    text = _claude_md().lower()
    assert "never fabricate research provenance" in text
    # The rule must enumerate the field types that may not be synthesized.
    for field in ["url", "job id", "posting", "contact", "email", "deadline"]:
        assert field in text, f"provenance rule missing field type: {field}"
    # Must require a successfully fetched source as the gate.
    assert "fetched" in text
    # Unverifiable is the prescribed fallback rather than synthesis.
    assert "unverifiable" in text


# --- T1-7 (repair): "successfully fetched source" is defined, snippets excluded ---

def test_claude_md_defines_successfully_fetched_source():
    """A search snippet must not count as a fetched source, or 'verified' is meaningless."""
    text = _claude_md().lower()
    # The phrase the rule gates on must be explicitly defined, not left undefined.
    assert "successfully fetched source" in text
    assert "snippet" in text, "definition must address search-result snippets"
    # Snippets/previews must be disqualified from the 'verified' label.
    assert "web_fetch_exa" in text or "webfetch" in text, "must name the fetch tool(s)"
    # A snippet-only field tops out at unverifiable, never verified.
    assert "unverifiable" in text


def test_recon_3_distinguishes_fetch_from_search_snippet():
    text = _recon_3().lower()
    # recon-3 must spell out that search returns leads, fetch returns sources.
    assert "snippet" in text
    assert "successfully fetched" in text
    # The fetch tools must be named so 'fetched' is operationally concrete.
    assert "web_fetch_exa" in text or "webfetch" in text
    # A snippet-only value must be capped at unverifiable.
    assert "unverifiable" in text


# --- T1-3 (repair): downstream consumers (composer-4) must respect confidence labels ---

def test_claude_md_binds_consumers_to_respect_confidence_labels():
    text = _claude_md().lower()
    # The rule must name composer-4 / downstream consumers explicitly.
    assert "composer-4" in text
    assert "consumer" in text
    # An inferred/unverifiable email must never enter a DM/outreach as a real address.
    assert "dm draft" in text
    # The consumer must warn the user and fall back to a verified channel.
    assert "visible warning" in text
    assert "fall back" in text
    # The consumer must not silently upgrade or drop the label.
    assert "may never upgrade" in text


def test_recon_3_flags_non_verified_emails_for_consumers():
    text = _recon_3()
    lower = text.lower()
    # recon-3 must emit a hard, visible flag on any non-verified email.
    assert "do not use as send channel" in lower
    # And name composer-4 as the consumer bound to respect it.
    assert "composer-4" in lower
    # Non-verified email must force a verified fallback channel.
    assert "fall back to a `verified` channel" in lower
    # Non-verified email must not enter a DM draft / outreach message as a real address.
    assert "may never enter a dm draft" in lower


# --- T1-3: verified vs inferred contact confidence, pattern emails never confirmed ---

def test_claude_md_separates_inferred_from_confirmed_contacts():
    text = _claude_md().lower()
    assert "inferred" in text
    assert "pattern" in text
    # A pattern-derived email must not be presentable as confirmed/verified.
    assert "never present an inferred contact detail as confirmed" in text


def test_recon_3_schema_has_email_confidence_labels():
    text = _recon_3()
    lower = text.lower()
    # The contact schema must carry an Email field with a confidence label that
    # distinguishes verified from inferred (pattern-guessed).
    assert "Email:" in text
    assert "confidence:" in lower
    assert "verified" in lower
    assert "inferred" in lower
    # Pattern-derived emails must be explicitly forbidden from "verified/confirmed".
    assert "naming pattern" in lower
    assert "verify before contact" in lower


# --- T4-4: subagents must not surface internal tool limitations to the user ---

def test_claude_md_forbids_tool_confessions():
    text = _claude_md().lower()
    assert "tool confessions" in text or "tool-architecture" in text
    # The concrete leaked phrasing from the finding must be named as forbidden.
    assert "i can only read files" in text
    assert "capability disclaimers" in text


def test_recon_3_does_not_leak_tool_limitations_on_failure():
    text = _recon_3().lower()
    assert "never surface internal tool limitations" in text
