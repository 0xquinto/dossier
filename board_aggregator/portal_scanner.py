"""Portal scanner — fetches job postings from ATS platform APIs.

Supports Greenhouse, Ashby, and Lever public APIs.
No authentication required for any endpoint.
"""

import re
from datetime import date, timedelta
from pathlib import Path

import requests as http_requests
import yaml

from board_aggregator.models import JobPosting

_TIMEOUT = 30
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str | None) -> str | None:
    """Remove HTML tags, collapse whitespace."""
    if not html:
        return None
    text = _TAG_RE.sub("", html)
    return " ".join(text.split()).strip() or None


# ---------------------------------------------------------------------------
# Greenhouse
# ---------------------------------------------------------------------------


def fetch_greenhouse(slug: str) -> list[JobPosting]:
    """Fetch all jobs from a Greenhouse job board.

    Endpoint: GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs
    Docs: https://developers.greenhouse.io/job-board.html
    """
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    try:
        resp = http_requests.get(url, timeout=_TIMEOUT)
        if resp.status_code != 200:
            print(f"[portal_scanner] Greenhouse {slug}: HTTP {resp.status_code}")
            return []
        data = resp.json()
    except Exception as e:
        print(f"[portal_scanner] Greenhouse {slug}: {e}")
        return []

    jobs: list[JobPosting] = []
    for item in data.get("jobs", []):
        is_remote = False
        for meta in (item.get("metadata") or []):
            if meta.get("name") == "Location Type" and meta.get("value"):
                is_remote = "remote" in str(meta["value"]).lower()

        jobs.append(
            JobPosting(
                title=item.get("title", ""),
                company=item.get("company_name", slug),
                source="greenhouse",
                job_url=item.get("absolute_url", ""),
                location=(item.get("location") or {}).get("name"),
                is_remote=is_remote,
                salary_min=None,
                salary_max=None,
                description=_strip_html(item.get("content")),
            )
        )

    return jobs


# ---------------------------------------------------------------------------
# Ashby
# ---------------------------------------------------------------------------


def _extract_ashby_salary(compensation: dict | None) -> dict:
    """Extract salary from Ashby compensation structure.

    Path: compensationTiers[0].components[] -> filter compensationType == "Salary"
    Returns dict with salary fields. Empty dict if no salary component found.
    Only includes keys that have actual values — lets Pydantic defaults handle the rest.
    """
    if not compensation:
        return {}

    tiers = compensation.get("compensationTiers", [])
    if not tiers:
        return {}

    for component in tiers[0].get("components", []):
        if component.get("compensationType") == "Salary":
            result: dict = {}
            if component.get("minValue") is not None:
                result["salary_min"] = component["minValue"]
            if component.get("maxValue") is not None:
                result["salary_max"] = component["maxValue"]
            if component.get("currencyCode"):
                result["salary_currency"] = component["currencyCode"]
            interval_raw = component.get("interval", "")
            if "YEAR" in interval_raw.upper():
                result["salary_interval"] = "yearly"
            elif "MONTH" in interval_raw.upper():
                result["salary_interval"] = "monthly"
            elif "HOUR" in interval_raw.upper():
                result["salary_interval"] = "hourly"
            return result

    return {}


def fetch_ashby(slug: str, company_name: str | None = None) -> list[JobPosting]:
    """Fetch all listed jobs from an Ashby job board.

    Endpoint: GET https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true
    Docs: https://developers.ashbyhq.com/docs/public-job-posting-api
    """
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    try:
        resp = http_requests.get(
            url, params={"includeCompensation": "true"}, timeout=_TIMEOUT
        )
        if resp.status_code != 200:
            print(f"[portal_scanner] Ashby {slug}: HTTP {resp.status_code}")
            return []
        data = resp.json()
    except Exception as e:
        print(f"[portal_scanner] Ashby {slug}: {e}")
        return []

    company = company_name or slug
    jobs: list[JobPosting] = []
    for item in data.get("jobs", []):
        if not item.get("isListed", True):
            continue

        salary = _extract_ashby_salary(item.get("compensation"))

        jobs.append(
            JobPosting(
                title=item.get("title", ""),
                company=company,
                source="ashby",
                job_url=item.get("jobUrl", ""),
                location=item.get("location"),
                is_remote=item.get("isRemote"),
                description=item.get("descriptionPlain"),
                **salary,
            )
        )

    return jobs


# ---------------------------------------------------------------------------
# Lever
# ---------------------------------------------------------------------------


def _extract_lever_salary(salary_range: dict | None) -> dict:
    """Extract salary from Lever salaryRange object.

    Returns dict with salary fields. Empty dict if salaryRange is null.
    Only includes keys that have actual values — lets Pydantic defaults handle the rest.
    """
    if not salary_range:
        return {}

    result: dict = {}
    if salary_range.get("min") is not None:
        result["salary_min"] = salary_range["min"]
    if salary_range.get("max") is not None:
        result["salary_max"] = salary_range["max"]
    if salary_range.get("currency"):
        result["salary_currency"] = salary_range["currency"]

    interval_raw = salary_range.get("interval", "")
    if "year" in interval_raw.lower():
        result["salary_interval"] = "yearly"
    elif "month" in interval_raw.lower():
        result["salary_interval"] = "monthly"
    elif "hour" in interval_raw.lower():
        result["salary_interval"] = "hourly"

    return result


def fetch_lever(slug: str, company_name: str | None = None) -> list[JobPosting]:
    """Fetch all postings from a Lever job board.

    Endpoint: GET https://api.lever.co/v0/postings/{slug}?mode=json
    Docs: https://github.com/lever/postings-api
    """
    url = f"https://api.lever.co/v0/postings/{slug}"
    try:
        resp = http_requests.get(url, params={"mode": "json"}, timeout=_TIMEOUT)
        if resp.status_code != 200:
            print(f"[portal_scanner] Lever {slug}: HTTP {resp.status_code}")
            return []
        data = resp.json()
    except Exception as e:
        print(f"[portal_scanner] Lever {slug}: {e}")
        return []

    if not isinstance(data, list):
        return []

    company = company_name or slug
    jobs: list[JobPosting] = []
    for item in data:
        categories = item.get("categories") or {}
        workplace = item.get("workplaceType") or ""
        salary = _extract_lever_salary(item.get("salaryRange"))

        jobs.append(
            JobPosting(
                title=item.get("text", ""),
                company=company,
                source="lever",
                job_url=item.get("hostedUrl", ""),
                location=categories.get("location"),
                is_remote=workplace.lower() == "remote",
                description=item.get("descriptionPlain"),
                **salary,
            )
        )

    return jobs


# ---------------------------------------------------------------------------
# Title filtering
# ---------------------------------------------------------------------------


def filter_by_title(
    jobs: list[JobPosting],
    positive: list[str],
    negative: list[str],
) -> list[JobPosting]:
    """Filter jobs by title keywords.

    A job passes if:
    - At least one positive keyword appears in the title (case-insensitive)
    - Zero negative keywords appear in the title (case-insensitive)
    """
    result: list[JobPosting] = []
    for job in jobs:
        title_lower = job.title.lower()
        has_positive = (
            any(kw.lower() in title_lower for kw in positive) if positive else True
        )
        has_negative = (
            any(kw.lower() in title_lower for kw in negative) if negative else False
        )
        if has_positive and not has_negative:
            result.append(job)
    return result


# ---------------------------------------------------------------------------
# scan_portals — orchestrator
# ---------------------------------------------------------------------------


def scan_portals(portals_path: str) -> list[JobPosting]:
    """Read portals.yml, scan ATS companies due for refresh, return postings.

    Skips companies where:
    - active is False
    - last_scanned is within scan_interval_days
    - ats is null (handled by scout-1 via Exa)

    After scanning, writes portals_path back to disk with updated fields:
    - last_scanned: set to today for each scanned company
    - last_had_openings: set to today if roles were found
    - active: set to False if disable_after_days exceeded with no openings

    Returns the list of JobPosting objects (unfiltered by title_filter;
    caller is responsible for filtering and dedup).
    """
    portals_file = Path(portals_path)
    data = yaml.safe_load(portals_file.read_text())

    config = data.get("config", {})
    scan_interval = config.get("scan_interval_days", 7)
    disable_after = config.get("disable_after_days", 30)

    today = date.today()
    all_jobs: list[JobPosting] = []

    fetchers = {
        "greenhouse": lambda slug, name: fetch_greenhouse(slug),
        "ashby": lambda slug, name: fetch_ashby(slug, company_name=name),
        "lever": lambda slug, name: fetch_lever(slug, company_name=name),
    }

    for company in data.get("companies", []):
        if not company.get("active", True):
            continue

        ats = company.get("ats")
        if ats is None:
            continue

        slug = company.get("slug")
        if not slug:
            continue

        # Check freshness
        last_scanned = company.get("last_scanned")
        if last_scanned:
            scanned_date = date.fromisoformat(str(last_scanned))
            if (today - scanned_date).days < scan_interval:
                continue

        # Fetch from the right ATS
        fetcher = fetchers.get(ats)
        if not fetcher:
            print(f"[portal_scanner] Unknown ATS '{ats}' for {company['name']}")
            continue

        name = company.get("name", slug)
        jobs = fetcher(slug, name)

        all_jobs.extend(jobs)

        # Update timestamps
        company["last_scanned"] = today.isoformat()
        if jobs:
            company["last_had_openings"] = today.isoformat()
        else:
            last_had = company.get("last_had_openings")
            if last_had:
                had_date = date.fromisoformat(str(last_had))
                if (today - had_date).days >= disable_after:
                    company["active"] = False
                    print(
                        f"[portal_scanner] Disabled {name}: no openings for {disable_after}+ days"
                    )

    # Write back updated portals.yml
    portals_file.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))

    return all_jobs
