import re
import time
from datetime import datetime, timezone

import requests as http_requests

from board_aggregator.models import JobPosting
from board_aggregator.scrapers import register
from board_aggregator.scrapers.base import BaseScraper

LISTING_URL = "https://www.reddit.com/r/{subs}/new.json"
USER_AGENT = "board-aggregator/1.0 (job-research-pipeline)"

MAX_RETRIES = 3
RETRY_BACKOFF = [2, 5, 10]

TIER_1_SUBS = ["forhire", "hiring", "jobbit", "remotejobs"]
_TIER_1_LOWER = frozenset(TIER_1_SUBS)
TIER_2_SUBS = [
    "WorkOnline", "webdev", "datascience", "freelance", "remotework",
    "digitalnomad", "Upwork", "freelanceWriters", "copywriting",
    "graphic_design", "learnprogramming", "VirtualAssistants",
    "socialmedia", "marketing", "CustomerSuccess", "startups",
]
ALL_SUBS = TIER_1_SUBS + TIER_2_SUBS

HIRING_SIGNAL = re.compile(
    r"\b(hiring|we.re hiring|job opening|open position|apply now|apply here|apply at)\b",
    re.IGNORECASE,
)

MAX_PAGES = 3


@register
class RedditJobsScraper(BaseScraper):
    name = "reddit"

    def scrape(self, queries: list[str], is_remote: bool = True, hours_old: int = 168) -> list[JobPosting]:
        raw_posts = self._fetch_listings()
        jobs: list[JobPosting] = []
        for post in raw_posts:
            parsed = self._parse_post(post)
            if parsed:
                jobs.append(parsed)
        return jobs

    def _fetch_listings(self) -> list[dict]:
        headers = {"User-Agent": USER_AGENT}
        subs = "+".join(ALL_SUBS)
        url = LISTING_URL.format(subs=subs)

        all_posts: list[dict] = []
        after: str | None = None

        for page in range(MAX_PAGES):
            params: dict[str, str | int] = {"limit": 100, "raw_json": 1}
            if after:
                params["after"] = after

            for attempt in range(MAX_RETRIES):
                try:
                    resp = http_requests.get(
                        url, headers=headers, params=params, timeout=30,
                    )
                    if resp.status_code == 429:
                        wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                        print(f"[reddit] Rate limited, waiting {wait}s (attempt {attempt + 1}/{MAX_RETRIES})")
                        time.sleep(wait)
                        continue
                    if resp.status_code != 200:
                        print(f"[reddit] Listing returned {resp.status_code}, stopping")
                        return all_posts

                    data = resp.json().get("data", {})
                    children = data.get("children", [])
                    all_posts.extend(child.get("data", {}) for child in children)
                    after = data.get("after")
                    break
                except Exception as e:
                    wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                    print(f"[reddit] Fetch error (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(wait)
                    else:
                        return all_posts

            if not after:
                break

        return all_posts

    def _parse_post(self, post: dict) -> JobPosting | None:
        title = post.get("title", "")
        selftext = post.get("selftext", "")
        author = post.get("author") or ""
        subreddit = post.get("subreddit", "")
        flair = post.get("link_flair_text") or ""

        # Skip rules
        if author in ("AutoModerator", "[deleted]"):
            return None
        if selftext in ("[removed]", "[deleted]"):
            return None
        if re.search(r"\[for\s*hire\]", title, re.IGNORECASE) or "for hire" in flair.lower():
            return None

        # Tier 2 filtering: require hiring signal
        if subreddit.lower() not in _TIER_1_LOWER:
            combined = f"{title} {selftext}"
            if not HIRING_SIGNAL.search(combined):
                return None

        # Company extraction
        company = self._extract_company(title, subreddit)

        # Remote detection
        combined = f"{title} {selftext}"
        is_remote = bool(re.search(r"\bremote\b", combined, re.IGNORECASE))

        # Salary extraction ($140K-$170K pattern)
        salary_match = re.search(r"\$(\d{2,3})[Kk]\s*[-\u2013]\s*\$?(\d{2,3})[Kk]", combined)
        salary_min = int(salary_match.group(1)) * 1000 if salary_match else None
        salary_max = int(salary_match.group(2)) * 1000 if salary_match else None

        # Date
        created_utc = post.get("created_utc")
        date_posted = None
        if created_utc:
            date_posted = datetime.fromtimestamp(created_utc, tz=timezone.utc).strftime("%Y-%m-%d")

        permalink = post.get("permalink", "")
        job_url = f"https://reddit.com{permalink}" if permalink else ""

        return JobPosting(
            title=title,
            company=company,
            source=self.name,
            job_url=job_url,
            location=None,
            is_remote=is_remote,
            salary_min=salary_min,
            salary_max=salary_max,
            date_posted=date_posted,
            description=selftext[:500] if selftext else None,
        )

    def _extract_company(self, title: str, subreddit: str) -> str:
        # 1. Pipe-separated: "[Tag] Role | Company | Location"
        #    When title has a bracketed prefix in the first segment, company is parts[1].
        #    Otherwise company is parts[0].
        parts = [p.strip() for p in title.split("|")]
        if len(parts) >= 2:
            first = parts[0]
            # If the first segment starts with a bracketed tag (e.g. "[Hiring]"),
            # the company is in the next segment.
            if re.match(r"^\[.*?\]", first):
                return parts[1].strip()
            # Otherwise strip any bracketed prefix from parts[0] and use that.
            candidate = re.sub(r"^\[.*?\]\s*", "", first).strip()
            if candidate:
                return candidate

        # 2. Bracketed: "[Company Name]" but not [Hiring]/[For Hire]
        bracket_match = re.search(r"\[([^\]]+)\]", title)
        if bracket_match:
            val = bracket_match.group(1)
            if val.lower() not in ("hiring", "for hire"):
                return val

        # 3. Bold markdown: "**Company Name**"
        bold_match = re.search(r"\*\*(.+?)\*\*", title)
        if bold_match:
            return bold_match.group(1)

        # 4. Preposition: "at Company" or "@ Company"
        at_match = re.search(r"(?:at|@)\s+([A-Z][\w\s&.]+)", title)
        if at_match:
            return at_match.group(1).strip()

        # 5. Fallback
        return f"r/{subreddit}"
