"""Static contract tests for the orchestration agent prompts (G6).

These guard the agent-prompt rules that make the first-run failure modes
impossible. They assert the load-bearing instruction text is present (and not
silently weakened) in lead-0, scout-1, and ranker-7. See first-user-session
findings:

- T4-2  lead-0 spawned a non-existent ``general-purpose`` agent.
- T1-5  lead-0 fabricated RUN_ID + meta.json timestamps (no real clock).
- T4-5  persona/scraper mismatch -> soft archetype-aware board recommendation.
- T2-7  output files exceed the read cap -> agents read the compact index.
- T2-2  80000hours must stay in the lead-0 preflight scraper list.
- T1-2  scout-1 synthesized roles from cookie-walled / unfetched pages.
- T1-1  scout-1 emitted fabricated (not parsed) URLs.
- T1-6  false-urgency framing on unverified deadlines.
- T4-7  foreground sleep polling -> run_in_background + Monitor.

The fix for an agent-prompt finding is unambiguous instruction text; these
are grep-able assertions over that text.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS = REPO_ROOT / ".claude" / "agents"
LEAD_0 = AGENTS / "lead-0.md"
SCOUT_1 = AGENTS / "scout-1.md"
RANKER_7 = AGENTS / "ranker-7.md"


def _lead_0() -> str:
    return LEAD_0.read_text()


def _scout_1() -> str:
    return SCOUT_1.read_text()


def _ranker_7() -> str:
    return RANKER_7.read_text()


# --- T4-2: lead-0 uses the real agent whitelist, never invents an agent ---

def test_lead_0_lists_real_agent_whitelist():
    text = _lead_0()
    lower = text.lower()
    # Exactly the 7 spawnable agents must be enumerated as the whitelist.
    for agent in [
        "primer-8", "scout-1", "ranker-7", "recon-3",
        "scripter-11", "composer-4", "discoverer-6",
    ]:
        assert agent in text, f"whitelist missing agent: {agent}"
    # The fabricated agent from the finding must be explicitly negated.
    assert "no `general-purpose` agent" in lower or "there is no general-purpose" in lower
    # And inventing an agent must be forbidden, not merely discouraged.
    assert "never spawn an agent type that is not in this list" in lower


def test_lead_0_does_not_endorse_general_purpose_as_valid():
    """The only mention of general-purpose must be the prohibition."""
    lower = _lead_0().lower()
    # No instruction to spawn it.
    assert "spawn the general-purpose" not in lower
    assert 'subagent_type:"general-purpose"' not in lower
    assert "subagent_type: general-purpose" not in lower


# --- T1-5: RUN_ID + timestamps come from a real `date -u` shell call ---

def test_lead_0_generates_run_id_from_date_shell_call():
    text = _lead_0()
    lower = text.lower()
    assert "date -u +%y-%m-%dt%h-%m-%s" in lower, "RUN_ID must come from date -u"
    assert "date -u +%y-%m-%dt%h:%m:%sz" in lower, "timestamps must come from date -u"
    # The model must be told not to invent timestamps.
    assert "never invent" in lower
    assert "fabricat" in lower  # 'fabricated' / 'fabrication'


def test_lead_0_completed_at_also_from_real_clock():
    lower = _lead_0().lower()
    # The completed_at update must re-run date -u, not round/guess.
    assert "completed_at" in lower
    # The date call appears at least twice (start + completion).
    assert lower.count("date -u +%y-%m-%dt%h:%m:%sz") >= 2


# --- T4-5: soft archetype-aware recommended board defaults, user override ---

def test_lead_0_soft_archetype_board_recommendation():
    text = _lead_0()
    lower = text.lower()
    assert "archetype" in lower
    # The routing must be SOFT (recommendation), never a hard exclusion.
    assert "recommend" in lower
    assert "never a hard exclusion" in lower
    assert "never silently drop a board" in lower
    # The user can always override the recommendation.
    assert "override" in lower
    # The exec/non-tech mis-ranking rationale must be present.
    assert "exec" in lower
    # archetype recorded for ranker-7 to consume.
    assert "candidate_archetype" in text


# --- T2-7: lead-0 points ranker-7 at the compact index, not the huge md ---

def test_lead_0_phase2_reads_compact_index():
    text = _lead_0()
    lower = text.lower()
    assert "all-postings-index.json" in text
    assert "read cap" in lower
    # Must explicitly say NOT the markdown for phase 2 input.
    assert "not the human-readable" in lower


# --- T2-2: 80000hours stays in the preflight scraper list ---

def test_lead_0_preflight_lists_80000hours():
    text = _lead_0()
    assert "80000hours" in text
    # The list is the full 13 registered scrapers (reddit removed).
    assert "13" in text


# --- T1-2 / T1-1: scout-1 never synthesizes roles or URLs from unfetched pages ---

def test_scout_1_records_no_verifiable_openings_on_blocked_page():
    text = _scout_1()
    lower = text.lower()
    # The blocked-page signals from the finding must be named.
    assert "cookie wall" in lower or "enable cookies" in lower
    assert "login" in lower
    # The prescribed record on a blocked page is "no verifiable openings".
    assert "no verifiable openings" in lower
    # Synthesis of roles must be forbidden.
    assert "do not synthesize" in lower or "never synthesize" in lower


def test_scout_1_only_emits_parsed_urls():
    text = _scout_1()
    lower = text.lower()
    # URL must be parsed from fetched body, not constructed/guessed.
    assert "parsed from" in lower or "read verbatim" in lower
    assert "do not construct or guess" in lower
    # The placeholder fallback when no URL was parsed.
    assert "(verify on careers page)" in lower
    # Bind to the project provenance contract.
    assert "never fabricate research provenance" in lower


# --- T1-6: no urgency / deadline language without an explicit parsed deadline ---

def test_scout_1_no_urgency_without_explicit_deadline():
    lower = _scout_1().lower()
    assert "urgency" in lower
    assert "explicit application deadline" in lower
    assert "do not infer" in lower or "never" in lower
    # The concrete fabricated-urgency phrases from the finding are named.
    assert "closes tomorrow" in lower
    assert "apply today" in lower


def test_ranker_7_no_urgency_without_explicit_deadline():
    lower = _ranker_7().lower()
    assert "urgency" in lower
    assert "deadline" in lower
    assert "fabrication" in lower
    # Inferred deadlines explicitly forbidden in any field incl. "Why pursue".
    assert "inferred deadline" in lower
    assert "closes tomorrow" in lower


# --- T2-7: ranker-7 reads the compact index, not the huge markdown ---

def test_ranker_7_reads_compact_index():
    text = _ranker_7()
    lower = text.lower()
    assert "all-postings-index.json" in text
    assert "read cap" in lower
    assert "not the human-readable" in lower or "not the" in lower
    # ranker-7 needs Bash to load the JSON index.
    assert "Bash" in text.split("---", 2)[1], "ranker-7 must declare Bash in frontmatter"


def test_ranker_7_consumes_archetype_from_meta():
    text = _ranker_7()
    lower = text.lower()
    assert "meta.json" in lower
    assert "candidate_archetype" in text


# --- T4-7: scout-1 uses run_in_background + Monitor, not foreground sleep ---

def test_scout_1_backgrounds_long_scrape_no_foreground_sleep():
    text = _scout_1()
    lower = text.lower()
    # Tools must include the backgrounding + polling tools.
    front = text.split("---", 2)[1]
    assert "run_in_background" in front
    assert "Monitor" in front
    # Prose must forbid foreground sleep and prescribe Monitor / until.
    assert "foreground" in lower and "sleep" in lower
    assert "monitor" in lower
    assert "until" in lower
