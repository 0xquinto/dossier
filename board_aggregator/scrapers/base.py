import sys
from abc import ABC, abstractmethod

from board_aggregator.models import JobPosting


def report_skips(name: str, skipped: int, attempted: int) -> None:
    """Emit ONE aggregate line when try_create dropped some postings.

    Per-posting skips stay graceful (the scraper keeps going); this is the
    aggregate signal so a mass validation failure (e.g. a renamed URL field
    dropping every posting) is visible instead of looking like "no matches."
    Silent when nothing was skipped.
    """
    if skipped:
        print(
            f"[{name}] skipped {skipped}/{attempted} postings: invalid/empty job_url",
            file=sys.stderr,
        )


class BaseScraper(ABC):
    name: str = "base"

    @abstractmethod
    def scrape(
        self,
        queries: list[str],
        is_remote: bool = True,
        hours_old: int = 168,
    ) -> list[JobPosting]:
        """Scrape job postings for the given queries. Returns list of JobPosting."""
        ...
