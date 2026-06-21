"""Regression: a posting with an empty/invalid job_url must be SKIPPED, not crash
the whole scrape (project rule: skip unverified jobs; never fabricate, never crash).

Scrapers route construction through JobPosting.try_create(...), which returns None
on an invalid URL instead of raising ValidationError. Driving the himalayas scraper
through its normal HTTP parse path with one bad item proves the bad item is dropped
while the valid items survive. Against direct JobPosting(...) construction this test
fails (the empty applicationLink raises and aborts the scrape).
"""

import responses

from board_aggregator.scrapers.himalayas import HimalayasScraper

# Two valid postings and one with an empty applicationLink (empty job_url).
# totalCount=3 with MAX_LIMIT=20 stops after a single page (offset 20 >= 3).
_API_RESPONSE_WITH_BAD_URL = {
    "offset": 0,
    "limit": 20,
    "totalCount": 3,
    "jobs": [
        {
            "title": "Valid Job One",
            "companyName": "GoodCo",
            "applicationLink": "https://himalayas.app/companies/goodco/jobs/valid-one",
            "locationRestrictions": ["United States"],
            "currency": "USD",
            "pubDate": 1774692720,
            "employmentType": "Full Time",
            "excerpt": "A real posting with a real link.",
        },
        {
            # Missing applicationLink -> job_url="" -> must be skipped, not crash.
            "title": "No URL Job",
            "companyName": "MysteryCo",
            "locationRestrictions": [],
            "currency": "USD",
            "pubDate": 1774692700,
            "employmentType": "Full Time",
            "excerpt": "This posting has no application link.",
        },
        {
            "title": "Valid Job Two",
            "companyName": "AlsoGoodCo",
            "applicationLink": "https://himalayas.app/companies/alsogoodco/jobs/valid-two",
            "locationRestrictions": ["Canada"],
            "currency": "USD",
            "pubDate": 1774692680,
            "employmentType": "Full Time",
            "excerpt": "Another real posting with a real link.",
        },
    ],
}


@responses.activate
def test_himalayas_skips_posting_with_empty_url(capsys):
    responses.add(
        responses.GET,
        "https://himalayas.app/jobs/api",
        json=_API_RESPONSE_WITH_BAD_URL,
        status=200,
    )

    scraper = HimalayasScraper()
    # Must not raise; the empty-URL posting is dropped, the two valid ones survive.
    jobs = scraper.scrape(["anything"])

    titles = [j.title for j in jobs]
    assert titles == ["Valid Job One", "Valid Job Two"]
    assert all(j.job_url for j in jobs)

    # I2: per-posting skips stay graceful, but the aggregate is announced ONCE
    # so a mass validation failure isn't mistaken for "no matches."
    err = capsys.readouterr().err
    assert "[himalayas] skipped 1/3 postings: invalid/empty job_url" in err


@responses.activate
def test_himalayas_no_skip_line_when_all_valid(capsys):
    all_valid = {
        "offset": 0,
        "limit": 20,
        "totalCount": 1,
        "jobs": [
            {
                "title": "Valid Job",
                "companyName": "GoodCo",
                "applicationLink": "https://himalayas.app/companies/goodco/jobs/valid",
                "locationRestrictions": ["United States"],
                "currency": "USD",
                "pubDate": 1774692720,
                "employmentType": "Full Time",
                "excerpt": "A real posting.",
            }
        ],
    }
    responses.add(
        responses.GET,
        "https://himalayas.app/jobs/api",
        json=all_valid,
        status=200,
    )

    scraper = HimalayasScraper()
    jobs = scraper.scrape(["anything"])

    assert [j.title for j in jobs] == ["Valid Job"]
    # Nothing skipped -> no noise.
    assert "skipped" not in capsys.readouterr().err
