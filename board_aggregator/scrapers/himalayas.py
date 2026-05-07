from datetime import datetime, timezone

import requests as http_requests

from board_aggregator.models import JobPosting
from board_aggregator.scrapers import register
from board_aggregator.scrapers.base import BaseScraper

BASE_URL = "https://himalayas.app"
API_URL = f"{BASE_URL}/jobs/api"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
MAX_LIMIT = 20  # API enforces max 20 per request


@register
class HimalayasScraper(BaseScraper):
    name = "himalayas"

    def scrape(
        self,
        queries: list[str],
        is_remote: bool = True,
        max_pages: int = 5,
        hours_old: int = 168,
    ) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        offset = 0

        for _ in range(max_pages):
            try:
                resp = http_requests.get(
                    API_URL,
                    params={"limit": MAX_LIMIT, "offset": offset},
                    headers={"User-Agent": USER_AGENT},
                    timeout=30,
                )
                if resp.status_code != 200:
                    print(f"[himalayas] API returned {resp.status_code}, skipping")
                    return jobs

                data = resp.json()
                page_jobs = data.get("jobs", [])
                if not page_jobs:
                    break

                for item in page_jobs:
                    jobs.append(
                        JobPosting(
                            title=item.get("title", ""),
                            company=item.get("companyName", ""),
                            source=self.name,
                            job_url=item.get("applicationLink", ""),
                            location=", ".join(item.get("locationRestrictions", [])) or "Worldwide",
                            is_remote=len(item.get("locationRestrictions", [])) == 0
                            or is_remote,
                            salary_min=item.get("minSalary"),
                            salary_max=item.get("maxSalary"),
                            salary_currency=item.get("currency") or "USD",
                            date_posted=self._unix_to_date(item.get("pubDate")),
                            job_type=item.get("employmentType"),
                            description=item.get("excerpt"),
                        )
                    )

                total = data.get("totalCount", 0)
                offset += MAX_LIMIT
                if offset >= total:
                    break

            except Exception as e:
                print(f"[himalayas] Error: {e}")
                break

        return jobs

    @staticmethod
    def _unix_to_date(ts: int | None) -> str | None:
        """Convert Unix timestamp (seconds) to ISO date string."""
        if ts is None:
            return None
        try:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            return dt.strftime("%Y-%m-%d")
        except (ValueError, OSError):
            return None
