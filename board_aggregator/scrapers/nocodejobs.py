import json
import re
import time
from datetime import datetime

import requests as http_requests
from bs4 import BeautifulSoup

from board_aggregator.models import JobPosting
from board_aggregator.scrapers import register
from board_aggregator.scrapers.base import BaseScraper

LISTINGS_URL = "https://www.nocodejobs.org/open-positions"
BASE_URL = "https://www.nocodejobs.org"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

MAX_RETRIES = 3
RETRY_BACKOFF = [2, 5, 10]

# Anchor inner text format observed in the rendered page:
#   "CompanyXxxTitle and LocationYyy MM/DD/YYYYEmployment TypeFULL_TIMESalaryUSD A-B per hour..."
# Values follow each label inline. We split with these label markers.
_DATE_RE = re.compile(r"(\d{2}/\d{2}/\d{4})")
_SALARY_RE = re.compile(
    r"([A-Z]{3})\s*(\d+(?:[.,]\d+)?)\s*-\s*(\d+(?:[.,]\d+)?)\s*(?:per\s+(hour|year|month|week|day))?",
    re.IGNORECASE,
)


@register
class NoCodeJobsScraper(BaseScraper):
    name = "nocodejobs"

    def scrape(self, queries: list[str], is_remote: bool = True, hours_old: int = 168) -> list[JobPosting]:
        html = self._fetch()
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        items = soup.select(".job-item")
        jobs: list[JobPosting] = []
        for item in items:
            parsed = self._parse_item(item)
            if parsed:
                jobs.append(parsed)
        return jobs

    def _fetch(self) -> str | None:
        for attempt in range(MAX_RETRIES):
            try:
                resp = http_requests.get(
                    LISTINGS_URL,
                    headers={"User-Agent": USER_AGENT},
                    timeout=30,
                )
                if resp.status_code != 200:
                    print(f"[nocodejobs] Listings returned {resp.status_code}")
                    return None
                return resp.text
            except Exception as e:
                wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                print(f"[nocodejobs] Fetch error (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(wait)
        return None

    def _parse_item(self, item) -> JobPosting | None:
        title = (item.get("data-position") or "").strip()
        if not title:
            return None

        location = (item.get("data-location") or "").strip() or None
        team = (item.get("data-team") or "").strip()  # "Remote" / "On-site" / etc.
        description = (item.get("data-description") or "").strip()

        # Anchor href + flat inner text contain company, date, employment type, salary
        anchor = item.find("a", href=True)
        anchor_text = anchor.get_text(" ", strip=True) if anchor else ""
        href = anchor["href"] if anchor else ""
        job_url = href if href.startswith("http") else f"{BASE_URL}{href}" if href else BASE_URL

        company = self._extract_after(anchor_text, "Company", stop="Title and Location")
        if not company:
            # Fallback: pull leading capitalized phrase from description
            m = re.match(r"([A-Z][\w&.\- ]{1,60}?)\s+is\s+(?:seeking|hiring)", description)
            company = m.group(1).strip() if m else ""
        if not company:
            return None

        # Date
        date_match = _DATE_RE.search(anchor_text)
        date_posted = None
        if date_match:
            try:
                d = datetime.strptime(date_match.group(1), "%m/%d/%Y")
                date_posted = d.strftime("%Y-%m-%d")
            except ValueError:
                pass

        # Employment type
        emp_type_raw = self._extract_after(anchor_text, "Employment Type", stop="Salary")
        job_type = None
        if emp_type_raw:
            t = emp_type_raw.upper()
            if "FULL" in t:
                job_type = "fulltime"
            elif "PART" in t:
                job_type = "parttime"
            elif "CONTRACT" in t or "FREELANCE" in t:
                job_type = "contract"
            elif "INTERN" in t:
                job_type = "internship"

        # Salary
        salary_min: float | None = None
        salary_max: float | None = None
        salary_currency = "USD"
        salary_interval = "yearly"
        sal_match = _SALARY_RE.search(anchor_text)
        if sal_match:
            salary_currency = sal_match.group(1).upper()
            try:
                salary_min = float(sal_match.group(2).replace(",", ""))
                salary_max = float(sal_match.group(3).replace(",", ""))
            except ValueError:
                pass
            period = (sal_match.group(4) or "").lower()
            if period == "hour":
                salary_interval = "hourly"
            elif period == "month":
                salary_interval = "monthly"
            elif period == "week":
                salary_interval = "weekly"
            elif period == "day":
                salary_interval = "daily"

        is_remote = "remote" in team.lower() or (location and "remote" in location.lower())

        # Tags from data-category JSON array (not surfaced as separate field, but
        # appended to description for downstream keyword matching).
        try:
            tags = json.loads(item.get("data-category") or "[]")
        except (json.JSONDecodeError, TypeError):
            tags = []
        desc_with_tags = description
        if tags:
            desc_with_tags = f"{description}\n\nTags: {', '.join(tags)}"

        return JobPosting(
            title=title,
            company=company,
            source=self.name,
            job_url=job_url,
            location=location or team or None,
            is_remote=bool(is_remote),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            salary_interval=salary_interval,
            date_posted=date_posted,
            job_type=job_type,
            description=desc_with_tags[:500] if desc_with_tags else None,
        )

    @staticmethod
    def _extract_after(text: str, label: str, stop: str | None = None) -> str:
        idx = text.find(label)
        if idx < 0:
            return ""
        start = idx + len(label)
        if stop:
            end = text.find(stop, start)
            if end > 0:
                return text[start:end].strip()
        return text[start:].strip()
