# Agent Job Research Pipeline

## What this project is

A job research pipeline that scrapes job postings, scores them against the user's skills, and finds hiring managers — with optional personalized pitch generation. Phases 1-3 run automatically; **Phase 4 (pitch) is skipped by default** and offered after the other phases finish. Anti-mass-apply: quality over quantity.

## Running the pipeline

```
claude --agent lead-0
```

## Agent names

Non-descriptive names to prevent Claude from inferring default behaviors:
- `lead-0` — pipeline orchestrator
- `scout-1` — Phase 1: job board scraping (board-aggregator CLI + Chrome)
- `applier-2` — application form answer generator (on-demand, human-in-the-loop)
- `recon-3` — Phase 3: contact + company research (Exa + Chrome)
- `composer-4` — Phase 4 (optional): DM drafts + outreach status + STAR+R story accumulation (reads scripter-11's video-script.md)
- `discoverer-6` — company discovery via Exa (populates portals.yml; lead-0 auto-offers it when portals.yml is missing/empty, or run standalone)
- `ranker-7` — Phase 2: fit scoring with archetype detection against skills-inventory.md
- `primer-8` — onboarding: prerequisites, Exa MCP, profile building (spawned by lead-0 when readiness check fails)
- `letter-5` — ATS cover letter generation (on-demand, keyword injection + SOAR proof points)
- `pdf-9` — tailored ATS PDF CV generation (on-demand, keyword injection + bullet reordering)
- `filler-10` — hybrid ATS submitter: API-first for Lever/Ashby, browser automation for Greenhouse/Workday/others (on-demand, human-in-the-loop)
- `scripter-11` — Phase 4 (optional): video pitch script generation (draft → 8-advisor critique → revise)

## board-aggregator CLI

Scout-1 calls the `board-aggregator` CLI (installed in `.venv/`) which scrapes 13 boards:
- python-jobspy: Indeed, LinkedIn
- Custom scrapers: Himalayas, We Work Remotely, HN Who's Hiring, HN Freelancer, CryptoJobsList, crypto.jobs, web3.career, CryptocurrencyJobs, RemoteOK, Reddit, Indie Hackers, No Code Jobs

Source code: `board_aggregator/` — registry-pattern scrapers with Pydantic models, dedup, CSV+MD output.

## Run versioning

Each pipeline run writes to a timestamped directory under `research/runs/`. The lead-0 orchestrator generates a `RUN_ID` at pipeline start and passes `RUN_DIR` to every subagent.

```
research/
  runs/
    2026-03-28T14-05-00/          # RUN_ID = ISO 8601, colons replaced with dashes
      meta.json                    # written by lead-0: timing, phase stats, queries
      phase-1-scrape/
      phase-2-rank/
      phase-3-contacts/{company-slug}/
      phase-4-pitch/{company-slug}/
    2026-03-27T09-22-11/          # previous run preserved
      ...
  latest -> runs/2026-03-28T14-05-00/   # symlink, always points to most recent run
```

**Rules:**
- lead-0 generates `RUN_ID` and computes `RUN_DIR=research/runs/$RUN_ID`
- lead-0 passes `RUN_DIR` to EVERY subagent prompt (not hardcoded in agent definitions)
- Subagents write ALL output under `$RUN_DIR/phase-X/`
- lead-0 updates the `research/latest` symlink after each successful run
- lead-0 writes `meta.json` at run start (partial) and updates it at run end (complete)
- Retention: keep last 5 runs. lead-0 prunes oldest before starting.

## Directory conventions

- `research/runs/$RUN_ID/phase-1-scrape/` — Scraped postings (created at runtime by scout-1)
- `research/runs/$RUN_ID/phase-2-rank/` — Scored and tiered opportunities (created by ranker-7)
- `research/runs/$RUN_ID/phase-3-contacts/[company-slug]/` — Contact profiles + company context (created by recon-3)
- `research/runs/$RUN_ID/phase-4-pitch/[company-slug]/` — Video scripts + DM drafts + outreach status (created by composer-4)
- `research/latest/` — Symlink to most recent run (updated by lead-0)
- `research/applications.md` — Persistent application tracker (mutable, lives outside runs)
- `research/interview-prep/story-bank.md` — Persistent STAR+R story bank (append-only across runs)

## Key input files

- `skills-inventory.md` — The user's complete skills inventory (input to Phase 2)
- `resume.md` — Tailored resume (input to Phase 4)
- `negotiation-playbook.md` — Salary negotiation scenario templates (input to applier-2, composer-4)
- `templates/states.yml` — Application status definitions (input to scripts/tracker.py)
- `templates/cv-template.html` — ATS PDF HTML template (input to pdf-9)

## Subagent output contract

ALL subagents MUST:
1. Write verbose output to `$RUN_DIR/` files (path provided by lead-0 in each prompt)
2. Return ONLY 1-2 sentence summaries to the lead agent
3. NEVER return raw data in responses

This constraint survives context compaction because it is in CLAUDE.md.

## Codebase Overview

4-phase Claude agent pipeline + Python scraping engine. Agents orchestrated by lead-0 (Opus), scrapers via `board_aggregator` Click CLI.

**Stack**: Python 3.12+, Click, Pydantic, python-jobspy, requests, feedparser, BeautifulSoup, Exa MCP, Claude-in-Chrome MCP
**Structure**: `.claude/agents/` (12 agent defs), `board_aggregator/` (13 scrapers, 13 boards), `tests/` (mocked HTTP), `scripts/` (tracker.py, generate-pdf.mjs, normalize-ats.mjs), `dashboard/` (Go TUI)

For detailed architecture, see [docs/CODEBASE_MAP.md](docs/CODEBASE_MAP.md).

## Forbidden patterns

- Never mass-apply or auto-submit applications
- Never send DMs automatically (human-in-the-loop always)
- Never fabricate skills or experience in pitch materials
- Never accumulate large data in agent context (write to files)
- Never edit the same file from multiple parallel agents
- Never write to `research/` root — always write under `research/runs/$RUN_ID/`
