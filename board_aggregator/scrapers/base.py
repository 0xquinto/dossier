from abc import ABC, abstractmethod

from board_aggregator.models import JobPosting


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
