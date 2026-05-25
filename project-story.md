---
name: "dossier"
oneLiner: "A 4-phase Claude agent pipeline that scrapes 11 job boards, scores postings against your skills, finds hiring managers, and drafts personalized pitches — anti-mass-apply by design."
domain: "Developer tooling / Job search automation"
---

## Timespan
- **First commit:** 2026-03-26
- **Last commit:** 2026-04-08
- **Total commits:** 79
- **Active days:** 9

## Arc

### Beginning
The project started on March 26, 2026 with application materials, a research agent pipeline spec, and profile update guides for LinkedIn, X, and GitHub. Within two days, the core scraping engine `board-aggregator` shipped as a CLI v0.1.0 covering 8 job boards, and all 5 initial subagent definitions were committed alongside CLAUDE.md.

### Middle
The week of March 28–31 was a consolidation and expansion phase: the scraper package was renamed to `board_aggregator`, a RemoteOK scraper added, run versioning introduced (timestamped `research/runs/$RUN_ID/` directories), and a skills inventory was refactored around an "agentic engineer" framing. On April 6 — the most commit-dense day — the project gained the Reddit scraper (19 subreddits, two-tier signal filtering), a full ATS portal scanner (Greenhouse, Ashby, Lever), the `discoverer-6` company-discovery agent, a setup wizard, CI/CD workflows, and packaging for PyPI. On April 7 all personal references were stripped from agent definitions, making the pipeline generic and shareable.

### End
April 8 brought the final burst of feature work: an `applier-2` form-filler agent, 6-archetype detection in the ranker, a STAR+R story bank, a salary negotiation playbook, an application tracker CLI (`scripts/tracker.py`) with merge/dedup, an ATS PDF generation pipeline (Playwright + HTML template + `pdf-9` agent), and a Go TUI dashboard built with Bubble Tea and Lipgloss. The pipeline grew from 5 agents to 9, and the subagent output contract — verbose data to files, 1-2 sentence summaries back to lead-0 — was codified as a core architectural principle.

## Key Milestones
| Date | Commit | Description |
|------|--------|-------------|
| 2026-03-26 | 3ad2a62 | Research agent pipeline spec established — defined the 4-phase scrape/rank/recon/pitch architecture |
| 2026-03-27 | 087b24d | All 5 initial subagent definitions committed with CLAUDE.md — pipeline orchestration scaffolding complete |
| 2026-03-28 | d490852 | board-aggregator CLI v0.1.0 with 8 verified scrapers and fixture-backed tests |
| 2026-03-29 | 129b033 | Run versioning introduced — timestamped `research/runs/$RUN_ID/` with symlink to latest |
| 2026-04-06 | 19a6758 | ATS portal scanner added (Greenhouse, Ashby, Lever) enabling direct company job-board polling |
| 2026-04-06 | 5b45210 | Reddit scraper added (19 subreddits, 2-tier hiring-signal filtering) — board count reaches 11 |
| 2026-04-08 | 8522bbc | Application tracker CLI shipped with merge/dedup and state machine |
| 2026-04-08 | 7920502 | Go TUI dashboard added (Bubble Tea + Lipgloss) for browsing tracked applications |

## Tech Stack
- Python 3.12+
- Click (CLI framework)
- Pydantic (data models)
- python-jobspy (Indeed + LinkedIn)
- requests / BeautifulSoup / feedparser (scrapers)
- Claude Code agents (lead-0 through pdf-9, Opus + Sonnet)
- Exa MCP (contact and company research)
- Playwright / Node.js (ATS PDF generation)
- Go / Bubble Tea / Lipgloss (TUI dashboard)
- pytest / responses library (test suite)
- GitHub Actions (CI matrix on Python 3.12+3.13; PyPI publish via OIDC)

## Metrics
| Metric | Value |
|--------|-------|
| Job boards scraped | 11 (Indeed, LinkedIn, Himalayas, We Work Remotely, HN Who's Hiring, CryptoJobsList, crypto.jobs, web3.career, CryptocurrencyJobs, RemoteOK, Reddit) |
| Claude agents defined | 9 (lead-0, scout-1, ranker-7, recon-3, composer-4, discoverer-6, primer-8, applier-2, pdf-9) |
| Test suite size | 97 tests across 15 files |
| Total codebase files | 90 (135k tokens) |
| Commits shipped | 79 over 9 active days |
| ATS platforms supported | 3 (Greenhouse, Ashby, Lever) |

## Lessons Learned
- Non-descriptive agent names (lead-0, scout-1, ranker-7) prevent Claude from inferring default behaviors from semantics — a deliberate constraint that improves pipeline predictability.
- Subagent output contracts enforced in CLAUDE.md (verbose data to files; 1-2 sentence summaries to orchestrator) survive context compaction and keep the orchestrator's context window manageable across long multi-phase runs.
- Separating run versioning (timestamped `research/runs/$RUN_ID/`) from persistent state (`research/applications.md`, `story-bank.md`) gives reproducible per-run artifacts without losing cross-run continuity.
