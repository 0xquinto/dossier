import re

import requests as http_requests
from bs4 import BeautifulSoup

from board_aggregator.models import JobPosting
from board_aggregator.scrapers import register
from board_aggregator.scrapers.base import BaseScraper

BASE_URL = "https://web3.career"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

PAGES = [
    f"{BASE_URL}/remote-jobs",
    f"{BASE_URL}/security+smart-contract-jobs",
    f"{BASE_URL}/solidity-jobs",
    f"{BASE_URL}/defi+security-jobs",
]


@register
class Web3CareerScraper(BaseScraper):
    name = "web3career"

    def scrape(self, queries: list[str], is_remote: bool = True, hours_old: int = 168) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        seen_urls: set[str] = set()

        for page_url in PAGES:
            try:
                resp = http_requests.get(
                    page_url,
                    headers={"User-Agent": USER_AGENT},
                    timeout=30,
                )
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")

                for row in soup.select("tr[onclick]"):
                    tds = row.find_all("td")
                    if len(tds) < 2:
                        continue

                    # Skip ad rows (no h2 in first td)
                    h2 = tds[0].find("h2")
                    if not h2:
                        continue

                    title = h2.get_text(strip=True)

                    # Company from h3 in second td
                    h3 = tds[1].find("h3")
                    company = h3.get_text(strip=True) if h3 else ""

                    # URL from onclick attribute
                    onclick = row.get("onclick", "")
                    url_match = re.search(r"'(/[^']+)'", onclick)
                    job_url = f"{BASE_URL}{url_match.group(1)}" if url_match else ""

                    if job_url in seen_urls:
                        continue
                    seen_urls.add(job_url)

                    # Location: search ONLY in the location td (tds[3]), not the whole row
                    # This avoids matching /remote-jobs badge links in the tags td
                    location = ""
                    is_job_remote = False
                    if len(tds) > 3:
                        loc_td = tds[3]
                        remote_link = loc_td.find("a", href="/remote-jobs")
                        if remote_link:
                            location = "Remote"
                            is_job_remote = True
                        else:
                            loc_link = loc_td.find("a", href=lambda h: h and "/web3-jobs-" in h)
                            if loc_link:
                                location = loc_link.get_text(strip=True)

                    # Salary from tds[4] <p> -- only if starts with $
                    salary_min, salary_max = None, None
                    if len(tds) > 4:
                        p = tds[4].find("p")
                        if p:
                            raw = p.get_text(strip=True)
                            if raw.startswith("$"):
                                salary_min, salary_max = self._parse_salary(raw)

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
                print(f"[web3career] Error on {page_url}: {e}")

        return jobs

    @staticmethod
    def _parse_salary(text: str) -> tuple[float | None, float | None]:
        """Parse salary like '$76k - $84k' or '$175k - $250k'."""
        if not text:
            return None, None
        match = re.search(r"\$(\d+)[Kk]\s*[-\u2013]\s*\$?(\d+)[Kk]", text)
        if match:
            return int(match.group(1)) * 1000, int(match.group(2)) * 1000
        return None, None
