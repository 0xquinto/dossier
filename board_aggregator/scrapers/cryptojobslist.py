import json
import re

import requests as http_requests

from board_aggregator.models import JobPosting
from board_aggregator.scrapers import register
from board_aggregator.scrapers.base import BaseScraper

BASE_URL = "https://cryptojobslist.com"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

CATEGORY_PAGES = [
    f"{BASE_URL}/",
    f"{BASE_URL}/operations",
    f"{BASE_URL}/remote",
    f"{BASE_URL}/smart-contract",
]


@register
class CryptoJobsListScraper(BaseScraper):
    name = "cryptojobslist"

    def scrape(self, queries: list[str], is_remote: bool = True, hours_old: int = 168) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        seen_ids: set[str] = set()

        for page_url in CATEGORY_PAGES:
            try:
                resp = http_requests.get(
                    page_url,
                    headers={"User-Agent": USER_AGENT},
                    timeout=30,
                )
                if resp.status_code != 200:
                    continue

                match = re.search(
                    r'id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                    resp.text,
                    re.DOTALL,
                )
                if not match:
                    continue

                data = json.loads(match.group(1))
                page_jobs = data.get("props", {}).get("pageProps", {}).get("jobs", [])

                for item in page_jobs:
                    job_id = item.get("id", "")
                    if job_id in seen_ids:
                        continue
                    seen_ids.add(job_id)

                    # Salary is a nested object with minValue/maxValue/currency/unitText
                    salary = item.get("salary")
                    salary_min = None
                    salary_max = None
                    salary_currency = "USD"
                    if isinstance(salary, dict):
                        salary_min = salary.get("minValue")
                        salary_max = salary.get("maxValue")
                        salary_currency = salary.get("currency", "USD")

                    # URL pattern: {seoSlug}-{id}
                    seo_slug = item.get("seoSlug", "")
                    job_url = f"{BASE_URL}/{seo_slug}-{job_id}" if seo_slug else ""

                    # Remote detection: `remote` field can be True, False, or None
                    is_job_remote = bool(item.get("remote"))

                    # Date from publishedAt ISO8601
                    published_at = item.get("publishedAt", "")
                    date_posted = published_at[:10] if published_at else None

                    jobs.append(
                        JobPosting(
                            title=item.get("jobTitle", ""),
                            company=item.get("companyName", ""),
                            source=self.name,
                            job_url=job_url,
                            location=item.get("jobLocation", "") or "Remote",
                            is_remote=is_job_remote,
                            salary_min=salary_min,
                            salary_max=salary_max,
                            salary_currency=salary_currency,
                            date_posted=date_posted,
                        )
                    )
            except Exception as e:
                print(f"[cryptojobslist] Error on {page_url}: {e}")

        return jobs
