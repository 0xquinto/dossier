"""Static contract tests for the anti-fabrication / provenance rules.

These guard the agent-prompt contract that other agents cite. They assert the
load-bearing rule text is present (and not silently weakened) in the project
CLAUDE.md and the recon-3 agent definition. See first-user-session findings
T1-7 (anti-fabrication too narrow), T1-3 (overconfident contact attribution),
and T4-4 (subagents leak internal tool architecture).

Rewritten per the Exa Agent design spec §3 (own-fetch verifies, grounding
leads): `verified` is earned by the agent's OWN fetched full page body +
verbatim match + source-domain consistent with the claim. Exa `output.grounding`
is a lead and an audit trace — necessary-but-not-sufficient, never upgrading a
field to `verified` on its own. Contact enrichment returns candidates, not
verified values; a pattern-derived email stays `inferred`. The earlier gate
named a specific fetch tool (`web_fetch_exa`); that string is no longer
required — the principle (own-fetch gate, grounding-insufficiency) is what the
contract enforces now. The verified/inferred/unverifiable labels are capability
constraints (an inferred/unverifiable email may never enter send-ready material)
and the composer-4 consumer rules are preserved verbatim.
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


# --- §3: the own-fetch gate. "verified" requires the AGENT'S OWN fetched page ---

def test_claude_md_defines_successfully_fetched_source():
    """A search snippet must not count as a fetched source, or 'verified' is meaningless."""
    text = _claude_md().lower()
    # The phrase the rule gates on must be explicitly defined, not left undefined.
    assert "successfully fetched source" in text
    assert "snippet" in text, "definition must address search-result snippets"
    # A snippet-only field tops out at unverifiable, never verified.
    assert "unverifiable" in text


def test_claude_md_requires_own_fetch_for_verified():
    """`verified` is earned by the agent's OWN fetch + verbatim + consistent domain."""
    text = _claude_md().lower()
    # The agent itself must have fetched the page (not a provider, not a snippet).
    assert "fetched the page yourself" in text or "fetched its full page body with" in text
    # Source domain must be consistent with the claim.
    assert "source domain is consistent with the claim" in text


def test_claude_md_grounding_is_necessary_but_not_sufficient():
    """Exa grounding is a lead + audit trace; it NEVER upgrades a field to verified alone."""
    text = _claude_md().lower()
    assert "grounding" in text
    assert "necessary-but-not-sufficient" in text
    # Grounding alone must never reach 'verified'.
    assert "never upgrades a field to `verified` on its own" in text
    # It is a lead / audit trace, not a verifier.
    assert "audit trace" in text
    assert "marking its own homework" in text


def test_claude_md_enrichment_returns_candidates_not_verified():
    """Contact enrichment yields candidates; pattern-derived email stays inferred."""
    text = _claude_md().lower()
    assert "enrichment returns candidates" in text
    # Provider-returned values are not verified on the provider's word.
    assert "candidate" in text
    # A pattern-derived email stays inferred.
    assert "pattern-derived email stays `inferred`" in text


def test_recon_3_distinguishes_fetch_from_search_snippet():
    text = _recon_3().lower()
    # recon-3 must spell out that search returns leads, fetch returns sources.
    assert "snippet" in text
    assert "successfully fetched" in text
    # The agent's OWN fetch is the gate, not a named provider tool.
    assert "fetch the candidate page yourself" in text or "you retrieved the page's full body" in text
    # A snippet-only value must be capped at unverifiable.
    assert "unverifiable" in text


def test_recon_3_grounding_leads_does_not_verify():
    """recon-3 must state Exa grounding leads but does not verify."""
    text = _recon_3().lower()
    assert "grounding" in text
    assert "necessary-but-not-sufficient" in text
    assert "never upgrades a field to `verified`" in text
    # Enrichment values are candidates, not verified.
    assert "candidate" in text


# --- Labels-as-capability-constraints + T1-3: downstream consumers (composer-4) ---

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
