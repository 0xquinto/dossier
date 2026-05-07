import math

from jobspy import scrape_jobs

from board_aggregator.models import JobPosting
from board_aggregator.scrapers import register
from board_aggregator.scrapers.base import BaseScraper


@register
class JobSpyScraper(BaseScraper):
    name = "jobspy"

    def scrape(
        self,
        queries: list[str],
        is_remote: bool = True,
        results_per_query: int = 50,
        hours_old: int = 168,
        country_indeed: str = "worldwide",
    ) -> list[JobPosting]:
        jobs: list[JobPosting] = []

        for query in queries:
            try:
                df = scrape_jobs(
                    site_name=["indeed", "linkedin"],
                    search_term=query,
                    google_search_term=f"{query} remote jobs",
                    location="Remote",
                    results_wanted=results_per_query,
                    hours_old=hours_old,
                    country_indeed=country_indeed,
                    is_remote=is_remote,
                )

                for _, row in df.iterrows():
                    jobs.append(
                        JobPosting(
                            title=row.get("title", ""),
                            company=row.get("company", ""),
                            source=str(row.get("site", "jobspy")),
                            job_url=str(row.get("job_url", "")),
                            location=str(row.get("location", "")),
                            is_remote=bool(row.get("is_remote", True)),
                            salary_min=self._safe_float(row.get("min_amount")),
                            salary_max=self._safe_float(row.get("max_amount")),
                            salary_currency=str(row.get("currency", "USD")),
                            salary_interval=str(row.get("interval", "yearly")),
                            date_posted=str(row.get("date_posted", "")),
                            job_type=str(row.get("job_type", "")),
                            description=str(row.get("description", ""))[:500],
                        )
                    )
            except Exception as e:
                print(f"[jobspy] Error on query '{query}': {e}")

        return jobs

    @staticmethod
    def _safe_float(val) -> float | None:
        if val is None:
            return None
        try:
            f = float(val)
            return None if math.isnan(f) else f
        except (ValueError, TypeError):
            return None
