"""Hiring Without Whiteboards signal.

Parses the community-maintained company list at
github.com/poteto/hiring-without-whiteboards (MIT) and matches it against
scraped postings by company name. A match is a lead, not a verified fact —
see the provenance caveat in README.md and `.claude/agents/ranker-7.md`.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import requests as http_requests
from pydantic import BaseModel

from board_aggregator.models import JobPosting

README_URL = "https://raw.githubusercontent.com/poteto/hiring-without-whiteboards/master/README.md"
DEFAULT_CACHE_PATH = Path.home() / ".cache" / "board-aggregator" / "hww-readme.md"
_TIMEOUT = 10

# Company entries: "- [Name](url)" optionally followed by " | Location" and
# " | Process". Both trailing segments are optional and independent.
_ENTRY_RE = re.compile(r"^- \[(?P<name>[^\]]+)\]\((?P<url>[^)]+)\)(?: \| (?P<rest>.*))?$")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]")


def _normalize(name: str) -> str:
    return _NON_ALNUM_RE.sub("", name.casefold())


class HWWCompany(BaseModel):
    name: str
    url: str
    location: str | None = None
    process: str | None = None

    @property
    def remote(self) -> bool | None:
        """Derived from `location`: True if it mentions remote (case-insensitive
        substring, so "Remote/ Singapore" and "SF / Remote" both count), False
        if `location` is present without the word, None if `location` is absent
        (the README simply didn't say)."""
        if self.location is None:
            return None
        return "remote" in self.location.casefold()


class HWWIndex:
    """Company list keyed by normalized name for O(1) lookup."""

    def __init__(self, companies: dict[str, HWWCompany] | None = None) -> None:
        self.companies = companies or {}

    def match(self, company: str) -> HWWCompany | None:
        return self.companies.get(_normalize(company))

    @classmethod
    def parse(cls, text: str) -> HWWIndex:
        """Parse the README's `## `-sectioned company list.

        Stops before `## Also see:` (a links appendix, not company entries).
        Everything before the first `## ` section (the intro, at `### `) is
        skipped since entry-shaped lines there aren't real listings.
        """
        companies: dict[str, HWWCompany] = {}
        in_section = False
        for line in text.splitlines():
            if line.startswith("## "):
                if line[3:].strip().lower().startswith("also see"):
                    break
                in_section = True
                continue
            if not in_section:
                continue
            m = _ENTRY_RE.match(line)
            if not m:
                continue
            rest = m.group("rest")
            location = process = None
            if rest is not None:
                parts = rest.split(" | ", 1)
                location = parts[0].strip() or None
                if len(parts) > 1:
                    process = parts[1].strip() or None
            company = HWWCompany(
                name=m.group("name").strip(),
                url=m.group("url").strip(),
                location=location,
                process=process,
            )
            companies[_normalize(company.name)] = company
        return cls(companies)

    @classmethod
    def load(cls, cache_path: Path | None = None, *, max_age_days: int = 7) -> HWWIndex:
        """Load the index, fetching README.md over the network only when the
        cache is stale or missing. Never raises: a fetch failure falls back to
        a stale cache, or an empty index, with a warning either way.
        """
        path = cache_path or DEFAULT_CACHE_PATH
        if path.exists():
            age_days = (time.time() - path.stat().st_mtime) / 86400
            if age_days <= max_age_days:
                return cls.parse(path.read_text(encoding="utf-8"))

        try:
            resp = http_requests.get(README_URL, timeout=_TIMEOUT)
            resp.raise_for_status()
            text = resp.text
        except Exception as e:
            if path.exists():
                print(f"[hww] fetch failed ({e}), using stale cache: {path}")
                return cls.parse(path.read_text(encoding="utf-8"))
            print(f"[hww] fetch failed ({e}), no cache available -- hww signal disabled this run")
            return cls()

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return cls.parse(text)


def enrich(jobs: list[JobPosting], index: HWWIndex) -> int:
    """Set hww_listed/hww_process on matched postings. Returns match count."""
    matched = 0
    for job in jobs:
        company = index.match(job.company)
        if company is None:
            continue
        job.hww_listed = True
        job.hww_process = company.process
        matched += 1
    return matched
