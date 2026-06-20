"""Portal scanner — fetches job postings from ATS platform APIs.

Supports Greenhouse, Ashby, Lever, and Workday public APIs.
No authentication required for any endpoint.
"""

import re
from datetime import date, timedelta
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlsplit

import requests as http_requests
import yaml

from board_aggregator.file_utils import _is_lock_error, atomic_write_text
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
# Workday (cxs JSON API)
# ---------------------------------------------------------------------------

# Workday careers URLs carry an optional locale segment (e.g. /en-US/) before
# the site name; skip it when picking the site so the cxs path is correct.
_LOCALE_RE = re.compile(r"^[a-z]{2}([-_][A-Za-z]{2})?$")

_WORKDAY_PAGE_LIMIT = 20  # API caps a page at 20 postings.
_WORKDAY_MAX_PAGES = 25  # Cap total pages (~500 postings) — never infinite-loop.


class WorkdaySite(NamedTuple):
    """Parsed components of a myworkdayjobs careers URL.

    host   = the netloc (e.g. nvidia.wd5.myworkdayjobs.com)
    tenant = first label of host (e.g. nvidia)
    site   = last non-locale path segment (e.g. NVIDIAExternalCareerSite)
    """

    scheme: str
    host: str
    tenant: str
    site: str


def _parse_workday_careers_url(careers_url: str) -> WorkdaySite | None:
    """Parse a myworkdayjobs careers URL into a WorkdaySite.

    Returns None if the URL is unusable (no host or no site segment).
    """
    parts = urlsplit(careers_url)
    host = parts.netloc
    if not host:
        return None
    tenant = host.split(".")[0]
    if not tenant:
        return None

    segments = [s for s in parts.path.split("/") if s and not _LOCALE_RE.match(s)]
    if not segments:
        return None
    site = segments[-1]

    scheme = parts.scheme or "https"
    return WorkdaySite(scheme, host, tenant, site)


def fetch_workday(careers_url: str, company_name: str) -> list[JobPosting]:
    """Fetch postings from a Workday (myworkdayjobs) careers site.

    Endpoint: POST https://{host}/wday/cxs/{tenant}/{site}/jobs
    Body: {"appliedFacets":{},"limit":20,"offset":0,"searchText":""}
    Paginates by incrementing offset by the per-page limit (20). Stops on the
    first of three conditions: (1) the page cap is hit
    (_WORKDAY_MAX_PAGES=25 pages × _WORKDAY_PAGE_LIMIT=20 ≈ 500 postings max —
    a tenant reporting more is truncated to 500), (2) `total` is reached, or
    (3) a page returns fewer than the limit. Fails soft (log + []) on a bad
    tenant/site (HTTP 422), other non-200, timeout, or parse error.
    """
    parsed = _parse_workday_careers_url(careers_url)
    if parsed is None:
        print(f"[portal_scanner] Workday {company_name}: unparseable careers_url {careers_url!r}")
        return []
    scheme, host, tenant, site = parsed
    endpoint = f"{scheme}://{host}/wday/cxs/{tenant}/{site}/jobs"

    jobs: list[JobPosting] = []
    offset = 0
    total: int | None = None
    for _ in range(_WORKDAY_MAX_PAGES):
        body = {
            "appliedFacets": {},
            "limit": _WORKDAY_PAGE_LIMIT,
            "offset": offset,
            "searchText": "",
        }
        try:
            resp = http_requests.post(endpoint, json=body, timeout=_TIMEOUT)
            if resp.status_code != 200:
                print(f"[portal_scanner] Workday {company_name}: HTTP {resp.status_code}")
                return []
            data = resp.json()
        except Exception as e:
            print(f"[portal_scanner] Workday {company_name}: {e}")
            return []

        if total is None:
            total = data.get("total")
        postings = data.get("jobPostings") or []
        for item in postings:
            external_path = item.get("externalPath") or ""
            bullets = item.get("bulletFields") or []
            req_id = bullets[0] if bullets else None
            job = JobPosting.try_create(
                title=item.get("title", ""),
                company=company_name,
                source="workday",
                job_url=f"{scheme}://{host}{external_path}",
                location=item.get("locationsText"),
                date_posted=item.get("postedOn"),
                description=f"Req {req_id}" if req_id else None,
            )
            if job is not None:
                jobs.append(job)

        offset += _WORKDAY_PAGE_LIMIT
        if len(postings) < _WORKDAY_PAGE_LIMIT:
            break
        if total is not None and offset >= total:
            break

    return jobs


# ---------------------------------------------------------------------------
# Generic careers_url fallback (ats == null)
# ---------------------------------------------------------------------------


def fetch_careers_url(careers_url: str, company_name: str) -> list[JobPosting]:
    """Best-effort fallback for companies with no supported ATS.

    Fetches the raw careers page and emits a single JobPosting pointing at it
    so the company isn't silently dropped. This is intentionally generic — it
    does NOT parse individual openings (a dedicated Workday/etc. scraper is
    deferred); it just confirms the page is reachable and surfaces the link
    for downstream Exa/manual follow-up. Returns [] if the page can't be
    fetched.
    """
    try:
        resp = http_requests.get(careers_url, timeout=_TIMEOUT)
        if resp.status_code != 200:
            print(
                f"[portal_scanner] careers_url {company_name}: HTTP {resp.status_code}"
            )
            return []
    except Exception as e:
        print(f"[portal_scanner] careers_url {company_name}: {e}")
        return []

    job = JobPosting.try_create(
        title=f"{company_name} — careers page",
        company=company_name,
        source="careers_url",
        job_url=careers_url,
    )
    if job is None:
        print(
            f"[portal_scanner] careers_url {company_name}: invalid careers_url "
            f"{careers_url!r}, skipping"
        )
        return []
    return [job]


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

    Companies with ats=null fall back to a best-effort generic fetch of
    careers_url (the page link is surfaced, not parsed into openings).

    After scanning, writes portals_path back to disk with updated fields:
    - last_scanned: set to today for each scanned company
    - last_had_openings: set to today if roles were found
    - active: set to False if disable_after_days exceeded with no openings

    Returns the list of JobPosting objects (unfiltered by title_filter;
    caller is responsible for filtering and dedup).
    """
    portals_file = Path(portals_path)
    data = yaml.safe_load(portals_file.read_text(encoding="utf-8"))

    config = data.get("config", {})
    scan_interval = config.get("scan_interval_days", 7)
    disable_after = config.get("disable_after_days", 30)

    today = date.today()
    all_jobs: list[JobPosting] = []

    # Workday is keyed on careers_url (host/tenant/site live there), not a slug.
    fetchers = {
        "greenhouse": lambda slug, url, name: fetch_greenhouse(slug),
        "ashby": lambda slug, url, name: fetch_ashby(slug, company_name=name),
        "lever": lambda slug, url, name: fetch_lever(slug, company_name=name),
        "workday": lambda slug, url, name: fetch_workday(url, name),
    }

    for company in data.get("companies", []):
        if not company.get("active", True):
            continue

        ats = company.get("ats")
        slug = company.get("slug")
        careers_url = company.get("careers_url")
        name = company.get("name") or slug or careers_url

        # ats=null companies fall back to a generic careers_url fetch.
        if ats is None and not careers_url:
            continue
        # Workday is keyed on careers_url; every other ATS needs a slug.
        if ats == "workday" and not careers_url:
            continue
        if ats is not None and ats != "workday" and not slug:
            continue

        # Check freshness
        last_scanned = company.get("last_scanned")
        if last_scanned:
            scanned_date = date.fromisoformat(str(last_scanned))
            if (today - scanned_date).days < scan_interval:
                continue

        # Guard the per-company dispatch: one fetcher blowing up (e.g. an edge
        # careers_url that slips past validation) must not abort the whole scan
        # or the remaining timestamp write-backs.
        try:
            if ats is None:
                # Best-effort generic fallback for unsupported ATS.
                jobs = fetch_careers_url(careers_url, name)
            else:
                fetcher = fetchers.get(ats)
                if not fetcher:
                    print(f"[portal_scanner] Unknown ATS '{ats}' for {name}")
                    continue
                jobs = fetcher(slug, careers_url, name)
        except Exception as e:
            print(f"[portal_scanner] {name}: fetch failed ({e}), skipping")
            continue

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

    # Write back updated portals.yml. The timestamp update is cosmetic, so a
    # locked/unwritable file must FAIL SOFT: scan results are still returned.
    # atomic_write_text writes UTF-8 to a sibling .tmp then os.replace()s it
    # into place (no half-written clobber) and retries on a lock before raising.
    dumped = yaml.dump(data, default_flow_style=False, sort_keys=False)
    try:
        atomic_write_text(portals_file, dumped)
    except OSError as exc:
        if _is_lock_error(exc) or "locked" in str(exc).lower():
            print(
                f"[portal_scanner] Could not save scan timestamps: {portals_file} "
                "is locked (likely open in an editor). Close the file to persist "
                "freshness state. Scan results are unaffected."
            )
        else:
            print(
                f"[portal_scanner] Could not save scan timestamps to {portals_file}: "
                f"{exc}. Scan results are unaffected."
            )

    return all_jobs
