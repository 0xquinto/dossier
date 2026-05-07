import feedparser

from board_aggregator.models import JobPosting
from board_aggregator.scrapers import register
from board_aggregator.scrapers.base import BaseScraper

FEED_URLS = [
    "https://weworkremotely.com/remote-jobs.rss",
    "https://weworkremotely.com/categories/remote-management-and-finance-jobs.rss",
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    "https://weworkremotely.com/categories/remote-contract-jobs.rss",
]


@register
class WeWorkRemotelyScraper(BaseScraper):
    name = "weworkremotely"

    def scrape(self, queries: list[str], is_remote: bool = True, hours_old: int = 168) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        seen_urls: set[str] = set()

        for feed_url in FEED_URLS:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries:
                    url = entry.get("link", "")
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)

                    raw_title = entry.get("title", "")
                    company, title = self._parse_title(raw_title)

                    # Region and type are bare custom tags (no namespace)
                    region = entry.get("region", "")
                    job_type = entry.get("type", "")

                    jobs.append(
                        JobPosting(
                            title=title,
                            company=company,
                            source=self.name,
                            job_url=url,
                            location=region or "Remote",
                            is_remote=True,
                            date_posted=entry.get("published", ""),
                            job_type=job_type,
                            description=entry.get("summary", ""),
                        )
                    )
            except Exception as e:
                print(f"[weworkremotely] Error fetching {feed_url}: {e}")

        return jobs

    @staticmethod
    def _parse_title(raw: str) -> tuple[str, str]:
        """WWR titles are 'Company Name: Job Title'. Split on FIRST colon only."""
        if ": " in raw:
            company, title = raw.split(": ", 1)
            return company.strip(), title.strip()
        return "", raw.strip()
