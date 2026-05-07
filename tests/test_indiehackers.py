import responses

from board_aggregator.scrapers.indiehackers import (
    ALGOLIA_URL,
    IndieHackersScraper,
)

ALGOLIA_RESPONSE = {
    "results": [
        {
            "hits": [
                {
                    "postId": "jobAd-abc1234567",
                    "objectID": "jobAd-abc1234567-1",
                    "title": "Hiring: Full-stack Engineer for Tuco AI",
                    "role": "Full-stack Engineer",
                    "productName": "Tuco AI",
                    "username": "tucoteam",
                    "body": "We are hiring a full-stack engineer. Remote-friendly.",
                    "locationName": "Remote",
                    "minSalary": 200,
                    "maxSalary": 800,
                    "paymentPeriod": "month",
                    "_tags": ["Part Time", "Remote", "Software Development"],
                    "createdTimestamp": 1775040000000,  # 2026-04-10
                    "closedTimestamp": 1777632000000,  # future
                },
                {
                    "postId": "jobAd-def9876543",
                    "objectID": "jobAd-def9876543-1",
                    "title": "Hiring: Co-Founder",
                    "role": "Co-Founder",
                    "productName": "Aerostack",
                    "body": "Looking for a technical co-founder.",
                    "locationName": "Remote",
                    "_tags": ["Full Time", "Remote"],
                    "createdTimestamp": 1774780800000,
                    "closedTimestamp": 1777372800000,  # future
                },
                {
                    # Job missing required fields — should be skipped
                    "postId": "jobAd-bad0000000",
                    "title": "",
                    "productName": "",
                },
            ]
        }
    ]
}


EMPTY_RESPONSE = {"results": [{"hits": []}]}


@responses.activate
def test_indiehackers_parses_open_jobs():
    # First page returns data; subsequent pages return empty to stop pagination.
    responses.add(responses.POST, ALGOLIA_URL, json=ALGOLIA_RESPONSE, status=200)
    responses.add(responses.POST, ALGOLIA_URL, json=EMPTY_RESPONSE, status=200)

    jobs = IndieHackersScraper().scrape([])

    assert len(jobs) == 2
    tuco = jobs[0]
    assert tuco.company == "Tuco AI"
    assert tuco.title == "Hiring: Full-stack Engineer for Tuco AI"
    assert tuco.source == "indiehackers"
    assert tuco.job_url == "https://www.indiehackers.com/post/jobAd-abc1234567"
    assert tuco.is_remote is True
    assert tuco.salary_min == 200
    assert tuco.salary_max == 800
    assert tuco.salary_interval == "monthly"
    assert tuco.job_type == "parttime"
    assert tuco.date_posted == "2026-04-01"  # 1775040000000 ms UTC


@responses.activate
def test_indiehackers_handles_missing_salary():
    responses.add(responses.POST, ALGOLIA_URL, json=ALGOLIA_RESPONSE, status=200)
    responses.add(responses.POST, ALGOLIA_URL, json=EMPTY_RESPONSE, status=200)

    jobs = IndieHackersScraper().scrape([])
    aero = next(j for j in jobs if j.company == "Aerostack")
    assert aero.salary_min is None
    assert aero.salary_max is None
    assert aero.job_type == "fulltime"


@responses.activate
def test_indiehackers_handles_api_error():
    responses.add(responses.POST, ALGOLIA_URL, json={"error": "boom"}, status=500)

    jobs = IndieHackersScraper().scrape([])
    assert jobs == []
