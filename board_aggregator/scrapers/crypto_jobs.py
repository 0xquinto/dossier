import re

import feedparser
from bs4 import BeautifulSoup

from board_aggregator.models import JobPosting
from board_aggregator.scrapers import register
from board_aggregator.scrapers.base import BaseScraper

FEED_URL = "https://crypto.jobs/feed/rss"


@register
class CryptoJobsScraper(BaseScraper):
    name = "crypto_jobs"

    def scrape(self, queries: list[str], is_remote: bool = True, hours_old: int = 168) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        try:
            feed = feedparser.parse(FEED_URL)
            for entry in feed.entries:
                # Extract structured fields from HTML description
                desc_html = entry.get("summary", "")
                fields = self._parse_description(desc_html)

                # Company from description (more reliable than title)
                company = fields.get("Company", "")

                # Title: strip "at Company" suffix from RSS title
                raw_title = entry.get("title", "")
                title = self._parse_title(raw_title, company)

                # Use <guid> for clean URL (no UTM params), fall back to <link>
                job_url = entry.get("id", "") or entry.get("link", "")

                location = fields.get("Location", "")
                job_type = fields.get("Type", "")

                jobs.append(
                    JobPosting(
                        title=title,
                        company=company,
                        source=self.name,
                        job_url=job_url,
                        location=location,
                        is_remote="remote" in location.lower(),
                        date_posted=entry.get("published", ""),
                        job_type=job_type,
                        description=desc_html[:500],
                    )
                )
        except Exception as e:
            print(f"[crypto_jobs] Error: {e}")

        return jobs

    @staticmethod
    def _parse_description(html: str) -> dict[str, str]:
        """Extract structured fields from description CDATA HTML.

        Format: <p><strong>Key:</strong> Value</p>
        Returns dict with keys: Company, Location, Salary, Type, Skills
        """
        soup = BeautifulSoup(html, "html.parser")
        fields: dict[str, str] = {}
        for p in soup.find_all("p"):
            strong = p.find("strong")
            if strong:
                key = strong.get_text(strip=True).rstrip(":")
                # Value is the text after the strong tag
                value = p.get_text(strip=True)[len(key) + 1:].strip()
                fields[key] = value
        return fields

    @staticmethod
    def _parse_title(raw: str, company: str) -> str:
        """Strip 'at Company' suffix and company prefix patterns from title."""
        title = raw
        # Remove "at Company" suffix
        if company and f" at {company}" in title:
            title = title.rsplit(f" at {company}", 1)[0]
        # Remove "Company \u2014 " prefix (some entries use em dash prefix)
        if company and title.startswith(f"{company} \u2014 "):
            title = title[len(f"{company} \u2014 "):]
            # If still has "at Company", strip it
            if f" at {company}" in title:
                title = title.rsplit(f" at {company}", 1)[0]
        return title.strip()
