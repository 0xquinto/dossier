# Agent Job Research Pipeline

## What this project is

A job research pipeline that scrapes job postings, scores them against the user's skills, and finds hiring managers, with optional personalized pitch generation. Phases 1-3 run automatically; **Phase 4 (pitch) is skipped by default** and offered after the other phases finish. Anti-mass-apply: quality over quantity.

## Running the pipeline

```
claude --agent lead-0
```

Requires the **Claude Code terminal CLI**. `lead-0` and the on-demand agents can only be launched as the primary agent via `claude --agent`, which only the CLI supports. The Claude Desktop app and claude.ai/code load the repo's `.claude/` config but offer no way to make a custom agent the main thread, so the pipeline cannot be started there (and `claude --remote` cloud sessions can't be combined with `--agent`). See the README "Claude Desktop & claude.ai" section.

## Agent names

Non-descriptive names to prevent Claude from inferring default behaviors:
- `lead-0`: pipeline orchestrator
- `scout-1`: Phase 1 job board scraping (board-aggregator CLI)
- `applier-2`: application form answer generator (on-demand, human-in-the-loop)
- `recon-3`: Phase 3 contact + company research (Exa)
- `composer-4`: Phase 4 (optional), DM drafts + outreach status + STAR+R story accumulation (reads scripter-11's video-script.md)
- `discoverer-6`: company discovery via Exa (populates portals.yml; lead-0 auto-offers it when portals.yml is missing/empty, or run standalone)
- `ranker-7`: Phase 2 fit scoring with archetype detection against skills-inventory.md
- `primer-8`: onboarding, covering prerequisites, the Exa credential (EXA_API_KEY), and profile building (spawned by lead-0 when readiness check fails)
- `letter-5`: ATS cover letter generation (on-demand, keyword injection + SOAR proof points)
- `pdf-9`: tailored ATS PDF CV generation (on-demand, keyword injection + bullet reordering)
- `filler-10`: ATS submitter, API submission for Lever/Ashby; delegates other ATSes to applier-2 for manual submission (on-demand, human-in-the-loop)
- `scripter-11`: Phase 4 (optional) video pitch script generation (draft, then 8-advisor critique, then revise)

## board-aggregator CLI

Scout-1 calls the `board-aggregator` CLI (installed in `.venv/`) which scrapes 13 boards:
- python-jobspy: Indeed, LinkedIn
- Custom scrapers: Himalayas, We Work Remotely, HN Who's Hiring, HN Freelancer, CryptoJobsList, crypto.jobs, web3.career, CryptocurrencyJobs, RemoteOK, Indie Hackers, No Code Jobs, 80,000 Hours

The source lives in `board_aggregator/`: registry-pattern scrapers with Pydantic models, dedup, CSV+MD output.

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

- `research/runs/$RUN_ID/phase-1-scrape/`: scraped postings (created at runtime by scout-1)
- `research/runs/$RUN_ID/phase-2-rank/`: scored and tiered opportunities (created by ranker-7)
- `research/runs/$RUN_ID/phase-3-contacts/[company-slug]/`: contact profiles + company context (created by recon-3)
- `research/runs/$RUN_ID/phase-4-pitch/[company-slug]/`: video scripts + DM drafts + outreach status (created by composer-4)
- `research/latest/`: symlink to most recent run (updated by lead-0)
- `research/applications.md`: persistent application tracker (mutable, lives outside runs)
- `research/interview-prep/story-bank.md`: persistent STAR+R story bank (append-only across runs)

## Key input files

- `skills-inventory.md`: the user's complete skills inventory (input to Phase 2)
- `resume.md`: tailored resume (input to Phase 4)
- `negotiation-playbook.md`: salary negotiation scenario templates (input to applier-2, composer-4)
- `templates/states.yml`: application status definitions (input to scripts/tracker.py)
- `templates/cv-template.html`: ATS PDF HTML template (input to pdf-9)

## Subagent output contract

ALL subagents MUST:
1. Write verbose output to `$RUN_DIR/` files (path provided by lead-0 in each prompt)
2. Return ONLY 1-2 sentence summaries to the lead agent
3. NEVER return raw data in responses
4. NEVER surface internal tool-architecture details, tool confessions, or capability disclaimers to the user. Phrases like "I do not have shell execution capability", "I can only read files / write files / fetch web pages / search the web", or any description of which tools you do or don't hold are forbidden in responses. If you cannot complete a task because of a tool limitation, report it as a user-facing task outcome (e.g., "could not find that information" / "that step could not be completed"), never as an implementation detail. lead-0 MUST reframe any subagent return that leaks such phrasing before surfacing it to the user.

This constraint survives context compaction because it is in CLAUDE.md.

## Codebase overview

4-phase Claude agent pipeline + Python scraping engine. Agents orchestrated by lead-0 (Opus), scrapers via `board_aggregator` Click CLI.

**Stack**: Python 3.12+, Click, Pydantic, python-jobspy, requests, feedparser, BeautifulSoup, exa-py (Exa Agent via the dossier-research CLI)
**Structure**: `.claude/agents/` (12 agent defs), `board_aggregator/` (13 scrapers, 13 boards), `tests/` (mocked HTTP), `scripts/` (tracker.py, generate-pdf.mjs, normalize-ats.mjs), `dashboard/` (Go TUI)

For detailed architecture, see [docs/CODEBASE_MAP.md](docs/CODEBASE_MAP.md).

## Forbidden patterns

- Never mass-apply or auto-submit applications
- Never send DMs automatically (human-in-the-loop always)
- Never fabricate skills or experience in pitch materials
- Never fabricate research provenance. NEVER emit a URL, job ID, posting, contact name, email address, contact title, or deadline that was not retrieved from a source you successfully fetched. If a source page fails to parse, returns no data, or does not contain the field, record it as `unverifiable`; never synthesize, guess, or pattern-fill the value.
- **Definition of a "successfully fetched source":** a source is successfully fetched ONLY when YOU (the agent) retrieved its full page body with a fetch/crawl tool and that body returned readable content containing the field verbatim, AND the source domain is consistent with the claim. A search-result snippet, title, preview, summary, or any excerpt returned by a search tool is NOT a fetched source: it is a lead to be fetched. A field that appears only in a search snippet and was never confirmed in a fetched page body is at most `unverifiable`; it may NEVER be labeled `verified`/`confirmed`. To label a field `verified` you must (a) have fetched the page yourself and (b) cite that fetched page's URL.
- **Exa grounding is necessary but not sufficient. It NEVER upgrades a field to `verified` on its own.** Exa Agent `output.grounding` (and any provider-returned citation, grounding trace, or source list) is a **lead**, telling you which sources to fetch next, and an **audit trace**. It is not a verifier. Letting Exa's self-report certify a field is "Exa marking its own homework": a citation existing does not mean the field is correct. A field supported ONLY by Exa grounding, and never confirmed by the agent's own fetched page body, is at most `unverifiable`. Own fetch + verbatim match + consistent source domain is the only path to `verified`.
- **Contact enrichment returns CANDIDATES, not verified values.** Emails/phones returned by an enrichment provider (Exa contact enrichment or similar) are candidate leads to be fetch-verified, never `verified` on the provider's word. A pattern-derived email stays `inferred`. Enrichment raises the hit rate of fetchable, real contacts; it does NOT lower the verification bar.
- Never present an inferred contact detail as confirmed. An email derived from a `firstname.lastname@domain` (or similar) naming pattern is NOT verified: it MUST be labeled `inferred` with the pattern noted, never `confirmed`/`verified`. Likewise never claim an action you did not observe in a fetched source (e.g. "she personally posted the job"). State only what the retrieved evidence supports.
- **Consumers must respect confidence labels (binds composer-4 and every downstream agent).** Any agent that reads contact data produced by recon-3 (`contacts.md`) MUST read the `confidence:` label on each field before using it. An `inferred` or `unverifiable` email MUST NEVER be placed into a DM draft, outreach message, mailto link, or any send-ready material as if it were a real address. If a contact's email is `inferred`/`unverifiable`/`not found`, the consuming agent: (a) MUST NOT use it as the outreach channel; fall back to a `verified` channel (LinkedIn/X) instead, and (b) MUST surface a visible warning to the user carrying the confidence label and the inferred pattern (e.g. "Email is INFERRED from a naming pattern; verify before sending"). A consumer may NEVER upgrade a field's confidence (turn `inferred` into `verified`) or silently drop the label. When in doubt, propagate the label verbatim.
- Never accumulate large data in agent context (write to files)
- Never edit the same file from multiple parallel agents
- Never write to `research/` root; always write under `research/runs/$RUN_ID/`
