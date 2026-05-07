import time

import requests as http_requests

from board_aggregator.scrapers import register
from board_aggregator.scrapers.hn_hiring import (
    ALGOLIA_DATE_URL,
    MAX_RETRIES,
    RETRY_BACKOFF,
    HNHiringScraper,
)


@register
class HNFreelancerScraper(HNHiringScraper):
    """Scrapes the monthly 'Ask HN: Freelancer? Seeking freelancer?' thread.

    Both this thread and 'Who is hiring?' are posted by the `whoishiring` account,
    so we reuse comment fetching/parsing from HNHiringScraper and only override
    thread discovery to filter by title.
    """

    name = "hn_freelancer"

    def _find_latest_thread(self) -> int | None:
        for attempt in range(MAX_RETRIES):
            try:
                resp = http_requests.get(
                    ALGOLIA_DATE_URL,
                    params={
                        "tags": "story,author_whoishiring",
                        "query": "Freelancer",
                        "restrictSearchableAttributes": "title",
                        "hitsPerPage": 5,
                    },
                    timeout=15,
                )
                hits = resp.json().get("hits", [])
                for hit in hits:
                    title = (hit.get("title") or "").lower()
                    if "freelancer" in title and "seeking freelancer" in title:
                        return int(hit["objectID"])
                return None
            except Exception as e:
                wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                print(f"[hn_freelancer] Error finding thread (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    print(f"[hn_freelancer] Retrying in {wait}s...")
                    time.sleep(wait)
        return None
