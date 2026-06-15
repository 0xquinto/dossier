import responses

from board_aggregator.scrapers.eighty_thousand_hours import (
    QUERY_URL,
    EightyThousandHoursScraper,
)
from tests.conftest import EIGHTY_THOUSAND_HOURS_API_RESPONSE


@responses.activate
def test_80000hours_scraper_parses_jobs():
    responses.add(
        responses.POST,
        QUERY_URL,
        json=EIGHTY_THOUSAND_HOURS_API_RESPONSE,
        status=200,
    )

    scraper = EightyThousandHoursScraper()
    jobs = scraper.scrape(["engineer"])

    assert len(jobs) == 2
    assert jobs[0].title == "Software Engineer, Core Technology"
    assert jobs[0].company == "UK Government, AI Security Institute"
    assert jobs[0].source == "80000hours"
    assert jobs[0].job_url.startswith("https://job-boards.eu.greenhouse.io/aisi/jobs/4386112101")
    assert jobs[0].location == "London, UK"


@responses.activate
def test_80000hours_scraper_sets_remote_from_location_type():
    responses.add(
        responses.POST,
        QUERY_URL,
        json=EIGHTY_THOUSAND_HOURS_API_RESPONSE,
        status=200,
    )

    scraper = EightyThousandHoursScraper()
    jobs = scraper.scrape(["any"])

    onsite = [j for j in jobs if j.company == "UK Government, AI Security Institute"][0]
    remote = [j for j in jobs if j.company == "Rethink Priorities"][0]
    assert onsite.is_remote is False
    assert remote.is_remote is True
    assert remote.location == "Remote, Global"


@responses.activate
def test_80000hours_scraper_converts_unix_timestamp():
    responses.add(
        responses.POST,
        QUERY_URL,
        json=EIGHTY_THOUSAND_HOURS_API_RESPONSE,
        status=200,
    )

    scraper = EightyThousandHoursScraper()
    jobs = scraper.scrape(["any"])

    assert jobs[0].date_posted is not None
    assert jobs[0].date_posted.startswith("2026-")


@responses.activate
def test_80000hours_scraper_dedups_across_queries():
    responses.add(
        responses.POST,
        QUERY_URL,
        json=EIGHTY_THOUSAND_HOURS_API_RESPONSE,
        status=200,
    )

    scraper = EightyThousandHoursScraper()
    # Two queries return the same hits; objectID dedup keeps each once.
    jobs = scraper.scrape(["engineer", "finance"])

    assert len(jobs) == 2


@responses.activate
def test_80000hours_scraper_handles_api_error():
    responses.add(
        responses.POST,
        QUERY_URL,
        json={"message": "rate limited"},
        status=429,
    )

    scraper = EightyThousandHoursScraper()
    jobs = scraper.scrape(["any"])

    assert jobs == []
