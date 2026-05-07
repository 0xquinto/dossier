import re
import time

import requests as http_requests

from board_aggregator.models import JobPosting
from board_aggregator.scrapers import register
from board_aggregator.scrapers.base import BaseScraper

ALGOLIA_URL = "https://hn.algolia.com/api/v1/search"
ALGOLIA_DATE_URL = "https://hn.algolia.com/api/v1/search_by_date"

MAX_RETRIES = 3
RETRY_BACKOFF = [2, 5, 10]  # seconds between retries


@register
class HNHiringScraper(BaseScraper):
    name = "hn_hiring"

    def scrape(self, queries: list[str], is_remote: bool = True, hours_old: int = 168) -> list[JobPosting]:
        thread_id = self._find_latest_thread()
        if not thread_id:
            print("[hn_hiring] No 'Who is hiring?' thread found")
            return []

        comments = self._fetch_comments(thread_id)
        # Only top-level comments are job posts: parent_id == story_id
        job_comments = [c for c in comments if c.get("parent_id") == c.get("story_id")]

        jobs: list[JobPosting] = []
        for comment in job_comments:
            text = comment.get("comment_text", "")
            parsed = self._parse_comment(text, comment)
            if parsed:
                jobs.append(parsed)

        return jobs

    def _find_latest_thread(self) -> int | None:
        """Find the most recent 'Who is hiring?' thread using search_by_date."""
        for attempt in range(MAX_RETRIES):
            try:
                resp = http_requests.get(
                    ALGOLIA_DATE_URL,
                    params={
                        "tags": "story,author_whoishiring",
                        "hitsPerPage": 1,
                    },
                    timeout=15,
                )
                hits = resp.json().get("hits", [])
                if hits:
                    return int(hits[0]["objectID"])
                # Valid response, no thread — don't retry
                return None
            except Exception as e:
                wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                print(f"[hn_hiring] Error finding thread (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    print(f"[hn_hiring] Retrying in {wait}s...")
                    time.sleep(wait)
        return None

    def _fetch_comments(self, thread_id: int) -> list[dict]:
        all_comments: list[dict] = []
        page = 0
        while True:
            hits = self._fetch_comments_page(thread_id, page)
            if hits is None:
                # All retries exhausted for this page
                break
            if not hits:
                # Empty page — we've reached the end
                break
            all_comments.extend(hits)
            # Check if there are more pages (Algolia includes nbPages)
            # We rely on empty hits to stop, but also cap at a sane limit
            page += 1
            if page > 20:
                break
        return all_comments

    def _fetch_comments_page(self, thread_id: int, page: int) -> list[dict] | None:
        """Fetch a single page of comments with retry logic. Returns None if all retries fail."""
        for attempt in range(MAX_RETRIES):
            try:
                resp = http_requests.get(
                    ALGOLIA_URL,
                    params={
                        "tags": f"comment,story_{thread_id}",
                        "hitsPerPage": 1000,
                        "page": page,
                    },
                    timeout=30,
                )
                data = resp.json()
                hits = data.get("hits", [])
                if page >= data.get("nbPages", 1):
                    return []
                return hits
            except Exception as e:
                wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                print(
                    f"[hn_hiring] Error fetching comments page {page} "
                    f"(attempt {attempt + 1}/{MAX_RETRIES}): {e}"
                )
                if attempt < MAX_RETRIES - 1:
                    print(f"[hn_hiring] Retrying in {wait}s...")
                    time.sleep(wait)
        return None

    def _parse_comment(self, text: str, comment: dict) -> JobPosting | None:
        if not text or len(text) < 20:
            return None

        # Strip HTML: replace <p> with newlines, remove tags, decode entities
        clean = self._strip_html(text)

        # HN job posts typically start with "Company | Role | Location | ..."
        first_line = clean.split("\n")[0]
        parts = [p.strip() for p in first_line.split("|")]

        company = parts[0] if len(parts) >= 1 else "Unknown"
        title = parts[1] if len(parts) >= 2 else first_line[:100]
        location = parts[2] if len(parts) >= 3 else ""

        # Extract company URL if present
        url_match = re.search(r"https?://[^\s<>)]+", text)
        job_url = url_match.group(0) if url_match else f"https://news.ycombinator.com/item?id={comment.get('objectID', '')}"

        is_remote = bool(re.search(r"\bREMOTE\b", clean, re.IGNORECASE))

        # Try to extract salary ($160K-$200K pattern)
        salary_match = re.search(r"\$(\d{2,3})[Kk]\s*[-\u2013]\s*\$?(\d{2,3})[Kk]", clean)
        salary_min = int(salary_match.group(1)) * 1000 if salary_match else None
        salary_max = int(salary_match.group(2)) * 1000 if salary_match else None

        return JobPosting(
            title=title,
            company=company,
            source=self.name,
            job_url=job_url,
            location=location,
            is_remote=is_remote,
            salary_min=salary_min,
            salary_max=salary_max,
            date_posted=comment.get("created_at", "")[:10],
            description=clean[:500],
        )

    @staticmethod
    def _strip_html(html: str) -> str:
        """Strip HTML tags and decode common entities from HN comment_text."""
        text = html.replace("<p>", "\n").replace("</p>", "")
        text = re.sub(r"<[^>]+>", "", text)
        text = (
            text.replace("&#x2F;", "/")
            .replace("&#x27;", "'")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
            .replace("&amp;", "&")
        )
        return text.strip()
