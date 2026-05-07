import time
from datetime import datetime, timezone

import requests as http_requests

from board_aggregator.models import JobPosting
from board_aggregator.scrapers import register
from board_aggregator.scrapers.base import BaseScraper

# Public search-only Algolia credentials embedded in the indiehackers.com page
# config (see /jobs HTML source). The app is a Firebase + Algolia SPA, and the
# `jobAds` index is browseable with these read-only keys.
ALGOLIA_APP_ID = "N86T1R3OWZ"
ALGOLIA_API_KEY = "5140dac5e87f47346abbda1a34ee70c3"
ALGOLIA_URL = f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/*/queries"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

MAX_RETRIES = 3
RETRY_BACKOFF = [2, 5, 10]
PAGE_SIZE = 50
MAX_PAGES = 4


@register
class IndieHackersScraper(BaseScraper):
    name = "indiehackers"

    def scrape(self, queries: list[str], is_remote: bool = True, hours_old: int = 168) -> list[JobPosting]:
        # IH auto-sets closedTimestamp = createdTimestamp + 30d at post time, so
        # "open" means closedTimestamp > now (Algolia-side filter).
        now_ms = int(time.time() * 1000)
        all_hits = self._fetch_all_pages(now_ms)
        jobs: list[JobPosting] = []
        for hit in all_hits:
            parsed = self._parse_hit(hit)
            if parsed:
                jobs.append(parsed)
        return jobs

    def _fetch_all_pages(self, now_ms: int) -> list[dict]:
        hits: list[dict] = []
        for page in range(MAX_PAGES):
            page_hits = self._fetch_page(page, now_ms)
            if page_hits is None:
                break  # all retries exhausted
            if not page_hits:
                break  # empty page = end
            hits.extend(page_hits)
        return hits

    def _fetch_page(self, page: int, now_ms: int) -> list[dict] | None:
        body = {
            "requests": [
                {
                    "indexName": "jobAds",
                    "params": (
                        f"hitsPerPage={PAGE_SIZE}&page={page}"
                        f"&filters=closedTimestamp%20%3E%20{now_ms}"
                    ),
                }
            ]
        }
        for attempt in range(MAX_RETRIES):
            try:
                resp = http_requests.post(
                    ALGOLIA_URL,
                    headers={
                        "X-Algolia-API-Key": ALGOLIA_API_KEY,
                        "X-Algolia-Application-Id": ALGOLIA_APP_ID,
                        "Content-Type": "application/json",
                        "User-Agent": USER_AGENT,
                    },
                    json=body,
                    timeout=20,
                )
                if resp.status_code != 200:
                    print(f"[indiehackers] Algolia returned {resp.status_code}, stopping")
                    return None
                results = resp.json().get("results", [])
                if not results:
                    return []
                return results[0].get("hits", [])
            except Exception as e:
                wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                print(f"[indiehackers] Fetch error page {page} (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(wait)
        return None

    def _parse_hit(self, hit: dict) -> JobPosting | None:
        post_id = hit.get("postId") or hit.get("objectID", "").split("-")[0:2]
        if isinstance(post_id, list):
            post_id = "-".join(post_id) if post_id else ""
        if not post_id:
            return None

        title = (hit.get("title") or hit.get("role") or "").strip()
        if not title:
            return None

        company = (hit.get("productName") or hit.get("username") or "").strip()
        if not company:
            return None

        location = (hit.get("locationName") or "").strip() or None
        body_text = hit.get("body") or ""

        # Remote detection: explicit tag or "remote" in location/body
        tags = [t.lower() for t in (hit.get("_tags") or [])]
        is_remote = bool(
            "remote" in tags
            or (location and "remote" in location.lower())
            or "remote" in body_text.lower()[:200]
        )

        # Salary normalization: IH stores raw numbers + paymentPeriod ("hour"/"year"/"month")
        min_s = hit.get("minSalary")
        max_s = hit.get("maxSalary")
        period = (hit.get("paymentPeriod") or "").lower()
        salary_min = float(min_s) if isinstance(min_s, (int, float)) and min_s > 0 else None
        salary_max = float(max_s) if isinstance(max_s, (int, float)) and max_s > 0 else None
        if period == "hour":
            interval = "hourly"
        elif period == "month":
            interval = "monthly"
        else:
            interval = "yearly"

        # Job type: scan tags for full/part time
        job_type = None
        for t in hit.get("_tags") or []:
            tl = t.lower()
            if "full time" in tl or "full-time" in tl:
                job_type = "fulltime"
                break
            if "part time" in tl or "part-time" in tl:
                job_type = "parttime"
                break
            if "contract" in tl or "freelance" in tl:
                job_type = "contract"
                break

        created_ms = hit.get("createdTimestamp")
        date_posted = None
        if isinstance(created_ms, (int, float)) and created_ms > 0:
            date_posted = datetime.fromtimestamp(
                created_ms / 1000.0, tz=timezone.utc
            ).strftime("%Y-%m-%d")

        return JobPosting(
            title=title,
            company=company,
            source=self.name,
            job_url=f"https://www.indiehackers.com/post/{post_id}",
            location=location,
            is_remote=is_remote,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_interval=interval,
            date_posted=date_posted,
            job_type=job_type,
            description=body_text[:500] if body_text else None,
        )
