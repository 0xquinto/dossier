import re

import requests as http_requests
from bs4 import BeautifulSoup

from board_aggregator.models import JobPosting
from board_aggregator.scrapers import register
from board_aggregator.scrapers.base import BaseScraper

BASE_URL = "https://cryptocurrencyjobs.co"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

CATEGORY_PAGES = [
    f"{BASE_URL}/",
    f"{BASE_URL}/operations/",
    f"{BASE_URL}/remote/",
]

SALARY_PATTERN = re.compile(r"[\$\u20ac\u00a3][\d,.]+[Kk]?\s*[\u2013\-]\s*[\$\u20ac\u00a3]?[\d,.]+[Kk]?|[\$\u20ac\u00a3][\d,.]+[Kk]")


@register
class CryptocurrencyJobsScraper(BaseScraper):
    name = "cryptocurrencyjobs"

    def scrape(self, queries: list[str], is_remote: bool = True, hours_old: int = 168) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        seen_urls: set[str] = set()

        for page_url in CATEGORY_PAGES:
            try:
                resp = http_requests.get(
                    page_url,
                    headers={"User-Agent": USER_AGENT},
                    timeout=30,
                )
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")

                # Find job cards: <li> elements containing h2 > a (title link)
                for li in soup.find_all("li"):
                    title_tag = li.select_one("h2 a")
                    if not title_tag:
                        continue

                    title = title_tag.get_text(strip=True)
                    href = title_tag.get("href", "")
                    job_url = f"{BASE_URL}{href}" if href.startswith("/") else href

                    if job_url in seen_urls:
                        continue
                    seen_urls.add(job_url)

                    # Company: h3 with or without <a>
                    company_tag = li.find("h3")
                    if company_tag:
                        company_link = company_tag.find("a")
                        company = company_link.get_text(strip=True) if company_link else company_tag.get_text(strip=True)
                    else:
                        company = ""

                    # Location: first <ul> inside li, each location in li > h4 > a
                    location = ""
                    is_job_remote = False
                    inner_uls = li.find_all("ul", recursive=False)
                    if inner_uls:
                        loc_links = inner_uls[0].find_all("a")
                        locations = [a.get_text(strip=True) for a in loc_links]
                        location = ", ".join(locations)
                        is_job_remote = any("remote" in loc.lower() for loc in locations)

                    # Salary: bare <span> matching currency pattern
                    salary_min, salary_max = None, None
                    for span in li.find_all("span", recursive=False):
                        text = span.get_text(strip=True)
                        if SALARY_PATTERN.search(text):
                            salary_min, salary_max = self._parse_salary(text)
                            break

                    jobs.append(
                        JobPosting(
                            title=title,
                            company=company,
                            source=self.name,
                            job_url=job_url,
                            location=location,
                            is_remote=is_job_remote,
                            salary_min=salary_min,
                            salary_max=salary_max,
                        )
                    )
            except Exception as e:
                print(f"[cryptocurrencyjobs] Error on {page_url}: {e}")

        return jobs

    @staticmethod
    def _parse_salary(text: str) -> tuple[float | None, float | None]:
        """Parse salary like '$100K - $180K' or '\u20ac50K - \u20ac75K'."""
        if not text:
            return None, None
        # Match ranges: $100K - $180K, \u20ac50K - \u20ac75K
        match = re.search(r"[\$\u20ac\u00a3](\d+\.?\d*)[Kk]\s*[\u2013\-]\s*[\$\u20ac\u00a3]?(\d+\.?\d*)[Kk]", text)
        if match:
            return float(match.group(1)) * 1000, float(match.group(2)) * 1000
        # Match single values: $120K
        single = re.search(r"[\$\u20ac\u00a3](\d+\.?\d*)[Kk]", text)
        if single:
            val = float(single.group(1)) * 1000
            return val, val
        return None, None
