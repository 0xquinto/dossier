import re
from datetime import datetime

import requests as http_requests

from board_aggregator.models import JobPosting
from board_aggregator.scrapers import register
from board_aggregator.scrapers.base import BaseScraper

API_URL = "https://remoteok.com/api"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


@register
class RemoteOKScraper(BaseScraper):
    name = "remoteok"

    def scrape(self, queries: list[str], is_remote: bool = True, hours_old: int = 168) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        seen_ids: set[str] = set()

        try:
            resp = http_requests.get(
                API_URL,
                headers={"User-Agent": USER_AGENT},
                timeout=30,
            )
            if resp.status_code != 200:
                print(f"[remoteok] API returned {resp.status_code}, skipping")
                return jobs

            data = resp.json()

            # First element is a legal notice / metadata dict, skip it
            listings = data[1:] if len(data) > 1 else data

            for item in listings:
                job_id = str(item.get("id", ""))
                if not job_id or job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                # Parse salary from salary_min / salary_max (integers) or
                # the description text when structured fields are absent.
                salary_min = self._to_float(item.get("salary_min"))
                salary_max = self._to_float(item.get("salary_max"))

                # Date: epoch or ISO string
                date_posted = self._parse_date(item.get("date"))

                # Location: RemoteOK is remote-only; location field is optional
                location = item.get("location", "") or "Remote"

                slug = item.get("slug", "")
                job_url = f"https://remoteok.com/remote-jobs/{job_id}" if not slug else f"https://remoteok.com/remote-jobs/{slug}"

                jobs.append(
                    JobPosting(
                        title=item.get("position", ""),
                        company=item.get("company", ""),
                        source=self.name,
                        job_url=job_url,
                        location=location,
                        is_remote=True,  # RemoteOK is a remote-only board
                        salary_min=salary_min,
                        salary_max=salary_max,
                        date_posted=date_posted,
                        job_type=item.get("job_type"),
                        description=item.get("description", ""),
                    )
                )
        except Exception as e:
            print(f"[remoteok] Error: {e}")

        return jobs

    @staticmethod
    def _to_float(val) -> float | None:
        """Coerce a salary value to float, returning None on failure."""
        if val is None:
            return None
        try:
            f = float(val)
            return f if f > 0 else None
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_date(raw) -> str | None:
        """Parse date from ISO 8601 string (e.g. '2026-03-25T12:00:00+00:00')."""
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(str(raw))
            return dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            # Fallback: grab first 10 chars if they look like a date
            s = str(raw)
            if re.match(r"\d{4}-\d{2}-\d{2}", s):
                return s[:10]
            return None
