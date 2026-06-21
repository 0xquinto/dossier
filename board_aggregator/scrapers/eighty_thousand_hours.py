from datetime import datetime, timezone

import requests as http_requests

from board_aggregator.models import JobPosting
from board_aggregator.scrapers import register
from board_aggregator.scrapers.base import BaseScraper, report_skips

# The 80,000 Hours job board (jobs.80000hours.org / app.80000hours.org) is
# served from the EA Work backend's public Algolia index -- the same search
# index the board's own frontend queries. The key below is a search-only key
# exposed in the board's client bundle, safe to ship.
APP_ID = "W6KM1UDIB3"
SEARCH_KEY = "d1d7f2c8696e7b36837d5ed337c4a319"
INDEX = "jobs_prod"
QUERY_URL = f"https://{APP_ID}-dsn.algolia.net/1/indexes/{INDEX}/query"
HITS_PER_PAGE = 100
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


@register
class EightyThousandHoursScraper(BaseScraper):
    name = "80000hours"

    def scrape(
        self,
        queries: list[str],
        is_remote: bool = True,
        max_pages: int = 3,
        hours_old: int = 168,
    ) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        seen: set[str] = set()
        attempted = 0
        skipped = 0

        headers = {
            "X-Algolia-Application-Id": APP_ID,
            "X-Algolia-API-Key": SEARCH_KEY,
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }

        for query in queries or [""]:
            for page in range(max_pages):
                try:
                    resp = http_requests.post(
                        QUERY_URL,
                        json={"query": query, "hitsPerPage": HITS_PER_PAGE, "page": page},
                        headers=headers,
                        timeout=30,
                    )
                    if resp.status_code != 200:
                        print(f"[80000hours] API returned {resp.status_code}, skipping")
                        break

                    data = resp.json()
                    hits = data.get("hits", [])
                    if not hits:
                        break

                    for item in hits:
                        obj_id = str(item.get("objectID", ""))
                        if obj_id and obj_id in seen:
                            continue
                        seen.add(obj_id)

                        attempted += 1
                        posting = self._to_posting(item)
                        if posting is None:
                            skipped += 1
                            continue
                        jobs.append(posting)

                    if page + 1 >= data.get("nbPages", 0):
                        break

                except Exception as e:
                    print(f"[80000hours] Error: {e}")
                    break

        report_skips(self.name, skipped, attempted)
        return jobs

    def _to_posting(self, item: dict) -> JobPosting | None:
        title = item.get("title", "")
        company = item.get("company_name") or (item.get("company") or {}).get("name", "")
        url = item.get("url_external", "")
        if not title or not url:
            return None

        location_types = item.get("tags_location_type") or []
        remote = any("remote" in str(t).lower() for t in location_types)

        return JobPosting.try_create(
            title=title,
            company=company,
            source=self.name,
            job_url=url,
            location=self._location(item) or "Unspecified",
            is_remote=remote,
            date_posted=self._unix_to_date(item.get("posted_at")),
            description=item.get("description_short") or None,
        )

    @staticmethod
    def _location(item: dict) -> str:
        for key in ("card_locations", "tags_location_80k", "tags_city", "tags_country"):
            vals = item.get(key)
            if vals:
                return ", ".join(str(v) for v in vals) if isinstance(vals, list) else str(vals)
        return ""

    @staticmethod
    def _unix_to_date(ts) -> str | None:
        """Convert Unix timestamp (seconds) to ISO date string."""
        if ts is None:
            return None
        try:
            return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
        except (ValueError, OSError, TypeError):
            return None
