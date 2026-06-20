import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import responses
import yaml

from board_aggregator.models import JobPosting
from board_aggregator.portal_scanner import (
    fetch_ashby,
    fetch_careers_url,
    fetch_greenhouse,
    fetch_lever,
    fetch_workday,
    filter_by_title,
    scan_portals,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Greenhouse
# ---------------------------------------------------------------------------


@responses.activate
def test_fetch_greenhouse_parses_jobs():
    fixture = json.loads((FIXTURES / "greenhouse_anthropic.json").read_text())
    responses.add(
        responses.GET,
        "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs",
        json=fixture,
        status=200,
    )

    jobs = fetch_greenhouse("anthropic")

    assert len(jobs) == 2
    assert jobs[0].title == "Account Executive, Academic Medical Centers"
    assert jobs[0].company == "Anthropic"
    assert jobs[0].source == "greenhouse"
    assert jobs[0].job_url == "https://job-boards.greenhouse.io/anthropic/jobs/5101832008"
    assert jobs[0].location == "New York City, NY; San Francisco, CA"
    assert jobs[0].salary_min is None
    assert jobs[0].salary_max is None


@responses.activate
def test_fetch_greenhouse_detects_remote_from_metadata():
    fixture = json.loads((FIXTURES / "greenhouse_anthropic.json").read_text())
    responses.add(
        responses.GET,
        "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs",
        json=fixture,
        status=200,
    )

    jobs = fetch_greenhouse("anthropic")

    assert jobs[0].is_remote is False  # Location Type = null
    assert jobs[1].is_remote is True  # Location Type = "Remote"


@responses.activate
def test_fetch_greenhouse_strips_html_from_description():
    fixture = json.loads((FIXTURES / "greenhouse_anthropic.json").read_text())
    responses.add(
        responses.GET,
        "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs",
        json=fixture,
        status=200,
    )

    jobs = fetch_greenhouse("anthropic")

    assert "<p>" not in (jobs[0].description or "")
    assert "<strong>" not in (jobs[1].description or "")
    assert "Build production LLM systems." in (jobs[1].description or "")


@responses.activate
def test_fetch_greenhouse_handles_api_error():
    responses.add(
        responses.GET,
        "https://boards-api.greenhouse.io/v1/boards/badslug/jobs",
        json={"error": "not found"},
        status=404,
    )

    jobs = fetch_greenhouse("badslug")

    assert jobs == []


# ---------------------------------------------------------------------------
# Ashby
# ---------------------------------------------------------------------------


@responses.activate
def test_fetch_ashby_parses_jobs():
    fixture = json.loads((FIXTURES / "ashby_ramp.json").read_text())
    responses.add(
        responses.GET,
        "https://api.ashbyhq.com/posting-api/job-board/ramp",
        json=fixture,
        status=200,
    )

    jobs = fetch_ashby("ramp", company_name="Ramp")

    # Should skip unlisted job
    assert len(jobs) == 1
    assert jobs[0].title == "AI Operations Specialist | Agentic Workflows"
    assert jobs[0].company == "Ramp"
    assert jobs[0].source == "ashby"
    assert jobs[0].job_url == "https://jobs.ashbyhq.com/ramp/63df0ffc-bdc6-40ba-906f-fe03378536b0"
    assert jobs[0].location == "New York, NY (HQ)"
    assert jobs[0].is_remote is True


@responses.activate
def test_fetch_ashby_extracts_salary():
    fixture = json.loads((FIXTURES / "ashby_ramp.json").read_text())
    responses.add(
        responses.GET,
        "https://api.ashbyhq.com/posting-api/job-board/ramp",
        json=fixture,
        status=200,
    )

    jobs = fetch_ashby("ramp", company_name="Ramp")

    assert jobs[0].salary_min == 150000
    assert jobs[0].salary_max == 250000
    assert jobs[0].salary_currency == "USD"
    assert jobs[0].salary_interval == "yearly"


@responses.activate
def test_fetch_ashby_handles_no_compensation():
    fixture = {
        "jobs": [
            {
                "id": "no-comp-job",
                "title": "Designer",
                "isListed": True,
                "isRemote": False,
                "workplaceType": "OnSite",
                "location": "NYC",
                "jobUrl": "https://jobs.ashbyhq.com/co/no-comp-job",
                "applyUrl": "https://jobs.ashbyhq.com/co/no-comp-job/application",
                "descriptionPlain": "Design things.",
                "compensation": None,
            }
        ],
        "apiVersion": "1",
    }
    responses.add(
        responses.GET,
        "https://api.ashbyhq.com/posting-api/job-board/nocomp",
        json=fixture,
        status=200,
    )

    jobs = fetch_ashby("nocomp", company_name="NoCo")

    assert len(jobs) == 1
    assert jobs[0].salary_min is None
    assert jobs[0].salary_max is None
    # When no salary data, Pydantic defaults apply (USD, yearly)
    assert jobs[0].salary_currency == "USD"
    assert jobs[0].salary_interval == "yearly"


@responses.activate
def test_fetch_ashby_handles_api_error():
    responses.add(
        responses.GET,
        "https://api.ashbyhq.com/posting-api/job-board/badslug",
        json={"error": "not found"},
        status=404,
    )

    jobs = fetch_ashby("badslug", company_name="Bad")

    assert jobs == []


# ---------------------------------------------------------------------------
# Lever
# ---------------------------------------------------------------------------


@responses.activate
def test_fetch_lever_parses_jobs():
    fixture = json.loads((FIXTURES / "lever_example.json").read_text())
    responses.add(
        responses.GET,
        "https://api.lever.co/v0/postings/example",
        json=fixture,
        status=200,
    )

    jobs = fetch_lever("example", company_name="ExampleCo")

    assert len(jobs) == 2
    assert jobs[0].title == "Staff ML Engineer"
    assert jobs[0].company == "ExampleCo"
    assert jobs[0].source == "lever"
    assert jobs[0].job_url == "https://jobs.lever.co/example/lever-job-001"
    assert jobs[0].location == "San Francisco, CA"


@responses.activate
def test_fetch_lever_extracts_salary():
    fixture = json.loads((FIXTURES / "lever_example.json").read_text())
    responses.add(
        responses.GET,
        "https://api.lever.co/v0/postings/example",
        json=fixture,
        status=200,
    )

    jobs = fetch_lever("example", company_name="ExampleCo")

    assert jobs[0].salary_min == 200000
    assert jobs[0].salary_max == 280000
    assert jobs[0].salary_currency == "USD"
    assert jobs[0].salary_interval == "yearly"


@responses.activate
def test_fetch_lever_handles_no_salary():
    fixture = json.loads((FIXTURES / "lever_example.json").read_text())
    responses.add(
        responses.GET,
        "https://api.lever.co/v0/postings/example",
        json=fixture,
        status=200,
    )

    jobs = fetch_lever("example", company_name="ExampleCo")

    assert jobs[1].salary_min is None
    assert jobs[1].salary_max is None


@responses.activate
def test_fetch_lever_detects_remote():
    fixture = json.loads((FIXTURES / "lever_example.json").read_text())
    responses.add(
        responses.GET,
        "https://api.lever.co/v0/postings/example",
        json=fixture,
        status=200,
    )

    jobs = fetch_lever("example", company_name="ExampleCo")

    assert jobs[0].is_remote is False  # hybrid
    assert jobs[1].is_remote is True  # remote


@responses.activate
def test_fetch_lever_handles_api_error():
    responses.add(
        responses.GET,
        "https://api.lever.co/v0/postings/badslug",
        json=[],
        status=404,
    )

    jobs = fetch_lever("badslug", company_name="Bad")

    assert jobs == []


# ---------------------------------------------------------------------------
# Workday (cxs JSON API)
# ---------------------------------------------------------------------------

WORKDAY_CAREERS_URL = "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"
WORKDAY_CXS_URL = (
    "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs"
)


@responses.activate
def test_fetch_workday_parses_postings():
    fixture = json.loads((FIXTURES / "workday_nvidia.json").read_text())
    # First page returns 20 (== limit) so the scraper would page again; the
    # second page is a short page (<limit) which stops pagination.
    responses.add(responses.POST, WORKDAY_CXS_URL, json=fixture, status=200)
    responses.add(
        responses.POST,
        WORKDAY_CXS_URL,
        json={"total": 2000, "jobPostings": []},
        status=200,
    )

    jobs = fetch_workday(WORKDAY_CAREERS_URL, "NVIDIA")

    # 20 postings from the fixture page; second page is empty.
    assert len(jobs) == 20
    first = jobs[0]
    assert first.title == "Foundry Engineering Yield Enhancement Engineer"
    assert first.company == "NVIDIA"
    assert first.source == "workday"
    assert first.location == "Taiwan, Hsinchu"
    # Absolute job_url = scheme+host + externalPath (relative).
    assert first.job_url == (
        "https://nvidia.wd5.myworkdayjobs.com/job/Taiwan-Hsinchu/"
        "Foundry-Engineering-Yield-Enhancement-Engineer_JR2015702"
    )
    # reqId from bulletFields[0] surfaced in the description.
    assert "JR2015702" in (first.description or "")


@responses.activate
def test_fetch_workday_returns_empty_on_422():
    # A wrong tenant/site 422s; the company must be skipped, not crash.
    responses.add(responses.POST, WORKDAY_CXS_URL, json={"error": "bad"}, status=422)

    jobs = fetch_workday(WORKDAY_CAREERS_URL, "NVIDIA")

    assert jobs == []


@responses.activate
def test_fetch_workday_stops_pagination_on_short_page():
    # A single page shorter than the limit must stop pagination after one call.
    page = {
        "total": 3,
        "jobPostings": [
            {
                "title": "AI Engineer",
                "externalPath": "/job/US-CA/AI-Engineer_JR1",
                "locationsText": "US, CA",
                "postedOn": "Posted Today",
                "bulletFields": ["JR1"],
            },
            {
                "title": "ML Engineer",
                "externalPath": "/job/US-NY/ML-Engineer_JR2",
                "locationsText": "US, NY",
                "postedOn": "Posted Today",
                "bulletFields": ["JR2"],
            },
        ],
    }
    responses.add(responses.POST, WORKDAY_CXS_URL, json=page, status=200)

    jobs = fetch_workday(WORKDAY_CAREERS_URL, "NVIDIA")

    assert len(jobs) == 2
    # Exactly one HTTP call — a short page stops pagination immediately.
    assert len(responses.calls) == 1


@responses.activate
def test_fetch_workday_paginates_until_total():
    # Two full-size pages then a short page exhausting `total`.
    full_page = {
        "total": 25,
        "jobPostings": [
            {
                "title": f"Engineer {i}",
                "externalPath": f"/job/US-CA/Engineer_JR{i}",
                "locationsText": "US, CA",
                "postedOn": "Posted Today",
                "bulletFields": [f"JR{i}"],
            }
            for i in range(20)
        ],
    }
    second_page = {
        "total": 25,
        "jobPostings": [
            {
                "title": f"Engineer {i}",
                "externalPath": f"/job/US-CA/Engineer_JR{i}",
                "locationsText": "US, CA",
                "postedOn": "Posted Today",
                "bulletFields": [f"JR{i}"],
            }
            for i in range(20, 25)
        ],
    }
    responses.add(responses.POST, WORKDAY_CXS_URL, json=full_page, status=200)
    responses.add(responses.POST, WORKDAY_CXS_URL, json=second_page, status=200)

    jobs = fetch_workday(WORKDAY_CAREERS_URL, "NVIDIA")

    assert len(jobs) == 25
    # Page 1 (full) triggers a second request; page 2 is short -> stop.
    assert len(responses.calls) == 2


@responses.activate
def test_fetch_workday_fails_soft_on_unparseable_url():
    # No network call expected; a non-myworkday URL with no path segment returns [].
    jobs = fetch_workday("https://nvidia.wd5.myworkdayjobs.com", "NVIDIA")

    assert jobs == []
    assert len(responses.calls) == 0


@responses.activate
def test_scan_portals_scans_workday(tmp_path):
    fixture = json.loads((FIXTURES / "workday_nvidia.json").read_text())
    responses.add(responses.POST, WORKDAY_CXS_URL, json=fixture, status=200)
    responses.add(
        responses.POST,
        WORKDAY_CXS_URL,
        json={"total": 2000, "jobPostings": []},
        status=200,
    )

    portals_path = _write_portals(
        tmp_path,
        [
            {
                "name": "NVIDIA",
                "domain": "nvidia.com",
                "ats": "workday",
                "slug": None,
                "careers_url": WORKDAY_CAREERS_URL,
                "active": True,
                "last_scanned": None,
                "last_had_openings": None,
            },
        ],
    )

    jobs = scan_portals(portals_path)

    assert any(j.source == "workday" for j in jobs)
    assert len(jobs) == 20

    # Timestamp stamped for the workday path.
    updated = yaml.safe_load(Path(portals_path).read_text())
    assert updated["companies"][0]["last_scanned"] == date.today().isoformat()


# ---------------------------------------------------------------------------
# Title filtering
# ---------------------------------------------------------------------------


def test_filter_by_title_matches_positive():
    jobs = [
        JobPosting(title="Senior AI Engineer", company="A", source="x", job_url="http://a"),
        JobPosting(title="Office Manager", company="B", source="x", job_url="http://b"),
        JobPosting(title="ML Platform Lead", company="C", source="x", job_url="http://c"),
    ]

    result = filter_by_title(jobs, positive=["AI", "ML"], negative=[])

    assert len(result) == 2
    assert result[0].title == "Senior AI Engineer"
    assert result[1].title == "ML Platform Lead"


def test_filter_by_title_excludes_negative():
    jobs = [
        JobPosting(title="AI Engineer Intern", company="A", source="x", job_url="http://a"),
        JobPosting(title="Senior AI Engineer", company="B", source="x", job_url="http://b"),
    ]

    result = filter_by_title(jobs, positive=["AI"], negative=["Intern"])

    assert len(result) == 1
    assert result[0].title == "Senior AI Engineer"


def test_filter_by_title_case_insensitive():
    jobs = [
        JobPosting(title="ai operations lead", company="A", source="x", job_url="http://a"),
    ]

    result = filter_by_title(jobs, positive=["AI"], negative=[])

    assert len(result) == 1


# ---------------------------------------------------------------------------
# scan_portals
# ---------------------------------------------------------------------------


def _write_portals(tmp_path, companies, config=None):
    """Helper to write a portals.yml for testing."""
    portals = {
        "config": config
        or {
            "scan_interval_days": 7,
            "disable_after_days": 30,
            "max_discovery_calls": 10,
            "icp_min_score": 6,
        },
        "title_filter": {
            "positive": ["AI", "Engineer"],
            "negative": ["Intern"],
        },
        "companies": companies,
    }
    path = tmp_path / "portals.yml"
    path.write_text(yaml.dump(portals, default_flow_style=False))
    return str(path)


@responses.activate
def test_scan_portals_fetches_from_correct_ats(tmp_path):
    fixture_gh = json.loads((FIXTURES / "greenhouse_anthropic.json").read_text())
    fixture_ashby = json.loads((FIXTURES / "ashby_ramp.json").read_text())

    responses.add(
        responses.GET,
        "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs",
        json=fixture_gh,
        status=200,
    )
    responses.add(
        responses.GET,
        "https://api.ashbyhq.com/posting-api/job-board/ramp",
        json=fixture_ashby,
        status=200,
    )

    portals_path = _write_portals(
        tmp_path,
        [
            {
                "name": "Anthropic",
                "domain": "anthropic.com",
                "ats": "greenhouse",
                "slug": "anthropic",
                "active": True,
                "last_scanned": None,
                "last_had_openings": None,
            },
            {
                "name": "Ramp",
                "domain": "ramp.com",
                "ats": "ashby",
                "slug": "ramp",
                "active": True,
                "last_scanned": None,
                "last_had_openings": None,
            },
        ],
    )

    jobs = scan_portals(portals_path)

    sources = {j.source for j in jobs}
    assert "greenhouse" in sources
    assert "ashby" in sources
    assert len(jobs) >= 3  # 2 Greenhouse + 1 listed Ashby


@responses.activate
def test_scan_portals_skips_inactive_companies(tmp_path):
    portals_path = _write_portals(
        tmp_path,
        [
            {
                "name": "Dead Corp",
                "domain": "dead.com",
                "ats": "greenhouse",
                "slug": "dead",
                "active": False,
                "last_scanned": None,
                "last_had_openings": None,
            },
        ],
    )

    jobs = scan_portals(portals_path)

    assert len(jobs) == 0


@responses.activate
def test_scan_portals_skips_recently_scanned(tmp_path):
    today = date.today().isoformat()
    portals_path = _write_portals(
        tmp_path,
        [
            {
                "name": "Fresh Corp",
                "domain": "fresh.com",
                "ats": "greenhouse",
                "slug": "fresh",
                "active": True,
                "last_scanned": today,
                "last_had_openings": today,
            },
        ],
    )

    jobs = scan_portals(portals_path)

    assert len(jobs) == 0


@responses.activate
def test_scan_portals_skips_null_ats_without_careers_url(tmp_path):
    portals_path = _write_portals(
        tmp_path,
        [
            {
                "name": "Custom Co",
                "domain": "custom.com",
                "ats": None,
                "slug": None,
                "careers_url": None,
                "active": True,
                "last_scanned": None,
                "last_had_openings": None,
            },
        ],
    )

    jobs = scan_portals(portals_path)

    assert len(jobs) == 0


@responses.activate
def test_scan_portals_updates_timestamps(tmp_path):
    fixture_gh = json.loads((FIXTURES / "greenhouse_anthropic.json").read_text())
    responses.add(
        responses.GET,
        "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs",
        json=fixture_gh,
        status=200,
    )

    portals_path = _write_portals(
        tmp_path,
        [
            {
                "name": "Anthropic",
                "domain": "anthropic.com",
                "ats": "greenhouse",
                "slug": "anthropic",
                "active": True,
                "last_scanned": None,
                "last_had_openings": None,
            },
        ],
    )

    scan_portals(portals_path)

    updated = yaml.safe_load(Path(portals_path).read_text())
    company = updated["companies"][0]
    assert company["last_scanned"] == date.today().isoformat()
    assert company["last_had_openings"] == date.today().isoformat()


@responses.activate
def test_scan_portals_disables_stale_company(tmp_path):
    responses.add(
        responses.GET,
        "https://boards-api.greenhouse.io/v1/boards/ghost/jobs",
        json={"jobs": []},
        status=200,
    )

    old_date = (date.today() - timedelta(days=31)).isoformat()
    portals_path = _write_portals(
        tmp_path,
        [
            {
                "name": "Ghost Corp",
                "domain": "ghost.com",
                "ats": "greenhouse",
                "slug": "ghost",
                "active": True,
                "last_scanned": (date.today() - timedelta(days=8)).isoformat(),
                "last_had_openings": old_date,
            },
        ],
    )

    scan_portals(portals_path)

    updated = yaml.safe_load(Path(portals_path).read_text())
    assert updated["companies"][0]["active"] is False


# ---------------------------------------------------------------------------
# Integration: run_all with portals
# ---------------------------------------------------------------------------


@responses.activate
def test_run_all_with_portals_integrates_results(tmp_path):
    """End-to-end: board scrapers + portal scanner -> unified dedup output."""
    from board_aggregator.runner import run_all

    fixture_ashby = json.loads((FIXTURES / "ashby_ramp.json").read_text())
    responses.add(
        responses.GET,
        "https://api.ashbyhq.com/posting-api/job-board/ramp",
        json=fixture_ashby,
        status=200,
    )

    portals_path = _write_portals(
        tmp_path,
        [
            {
                "name": "Ramp",
                "domain": "ramp.com",
                "ats": "ashby",
                "slug": "ramp",
                "active": True,
                "last_scanned": None,
                "last_had_openings": None,
            },
        ],
    )

    output_dir = tmp_path / "output"

    with patch("board_aggregator.runner.get_all_scrapers", return_value=[]):
        jobs = run_all(
            queries=["test"],
            output_dir=output_dir,
            portals_path=portals_path,
        )

    # Should have portal results (1 listed Ashby job matching title filter "AI")
    assert len(jobs) >= 1
    assert any(j.source == "ashby" for j in jobs)

    # Output files should exist
    assert (output_dir / "all-postings.md").exists()
    assert (output_dir / "all-postings.csv").exists()

    # portals.yml should be updated
    updated = yaml.safe_load(Path(portals_path).read_text())
    assert updated["companies"][0]["last_scanned"] == date.today().isoformat()


# ---------------------------------------------------------------------------
# T2-3 — careers_url fallback for ats=null companies
# ---------------------------------------------------------------------------


@responses.activate
def test_fetch_careers_url_returns_link_on_success():
    responses.add(
        responses.GET,
        "https://workdayco.com/careers",
        body="<html><body>We are hiring</body></html>",
        status=200,
    )

    jobs = fetch_careers_url("https://workdayco.com/careers", "Workday Co")

    assert len(jobs) == 1
    assert jobs[0].company == "Workday Co"
    assert jobs[0].source == "careers_url"
    assert jobs[0].job_url == "https://workdayco.com/careers"


@responses.activate
def test_fetch_careers_url_fails_soft_on_http_error():
    responses.add(
        responses.GET,
        "https://broken.com/careers",
        status=500,
    )

    jobs = fetch_careers_url("https://broken.com/careers", "Broken Co")

    assert jobs == []


@responses.activate
def test_fetch_careers_url_skips_invalid_url(capsys):
    # The page fetches fine, but the careers_url fails JobPosting validation
    # (e.g. a non-http(s) scheme the user typed). try_create returns None, so
    # the fetcher must skip (return []) instead of crashing the raw constructor.
    responses.add(
        responses.GET,
        "https://customco.com/careers",
        body="<html>hiring</html>",
        status=200,
    )

    with patch(
        "board_aggregator.portal_scanner.JobPosting.try_create",
        return_value=None,
    ):
        jobs = fetch_careers_url("https://customco.com/careers", "Custom Co")

    assert jobs == []
    out = capsys.readouterr().out
    assert "invalid careers_url" in out


@responses.activate
def test_scan_portals_does_not_raise_on_invalid_careers_url(tmp_path):
    # A user-edited portals.yml careers_url that fails model validation for an
    # ats=null company must fail soft: [] for that company, no exception, and
    # the scan still completes and stamps the timestamp.
    responses.add(
        responses.GET,
        "https://customco.com/careers",
        body="<html>hiring</html>",
        status=200,
    )

    portals_path = _write_portals(
        tmp_path,
        [
            {
                "name": "Custom Co",
                "domain": "customco.com",
                "ats": None,
                "slug": None,
                "careers_url": "https://customco.com/careers",
                "active": True,
                "last_scanned": None,
                "last_had_openings": None,
            },
        ],
    )

    with patch(
        "board_aggregator.portal_scanner.JobPosting.try_create",
        return_value=None,
    ):
        jobs = scan_portals(portals_path)

    assert jobs == []
    # Timestamp still written for the company despite the invalid URL.
    updated = yaml.safe_load(Path(portals_path).read_text())
    assert updated["companies"][0]["last_scanned"] == date.today().isoformat()


@responses.activate
def test_scan_portals_contains_per_company_fetcher_exception(tmp_path):
    # One company's fetcher exploding must not abort the scan: the other
    # company still scans and gets its timestamp written.
    fixture_gh = json.loads((FIXTURES / "greenhouse_anthropic.json").read_text())
    responses.add(
        responses.GET,
        "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs",
        json=fixture_gh,
        status=200,
    )

    portals_path = _write_portals(
        tmp_path,
        [
            {
                "name": "Boom Corp",
                "domain": "boom.com",
                "ats": "greenhouse",
                "slug": "boom",
                "active": True,
                "last_scanned": None,
                "last_had_openings": None,
            },
            {
                "name": "Anthropic",
                "domain": "anthropic.com",
                "ats": "greenhouse",
                "slug": "anthropic",
                "active": True,
                "last_scanned": None,
                "last_had_openings": None,
            },
        ],
    )

    real_fetch_greenhouse = fetch_greenhouse

    def exploding_greenhouse(slug):
        if slug == "boom":
            raise RuntimeError("fetcher blew up")
        return real_fetch_greenhouse(slug)

    with patch(
        "board_aggregator.portal_scanner.fetch_greenhouse",
        side_effect=exploding_greenhouse,
    ):
        jobs = scan_portals(portals_path)

    # Anthropic still scanned despite Boom Corp's fetcher raising.
    assert any(j.company == "Anthropic" for j in jobs)

    updated = yaml.safe_load(Path(portals_path).read_text())
    companies = {c["name"]: c for c in updated["companies"]}
    # The exploding company was skipped (no timestamp), the healthy one scanned.
    assert companies["Boom Corp"]["last_scanned"] is None
    assert companies["Anthropic"]["last_scanned"] == date.today().isoformat()


@responses.activate
def test_scan_portals_falls_back_to_careers_url_for_null_ats(tmp_path):
    responses.add(
        responses.GET,
        "https://customco.com/careers",
        body="<html><body>Open roles</body></html>",
        status=200,
    )

    portals_path = _write_portals(
        tmp_path,
        [
            {
                "name": "Custom Co",
                "domain": "customco.com",
                "ats": None,
                "slug": None,
                "careers_url": "https://customco.com/careers",
                "active": True,
                "last_scanned": None,
                "last_had_openings": None,
            },
        ],
    )

    jobs = scan_portals(portals_path)

    # ats=null no longer silently skipped: careers_url is fetched and surfaced.
    assert len(jobs) == 1
    assert jobs[0].source == "careers_url"
    assert jobs[0].job_url == "https://customco.com/careers"

    # Timestamp still stamped for the fallback path.
    updated = yaml.safe_load(Path(portals_path).read_text())
    assert updated["companies"][0]["last_scanned"] == date.today().isoformat()


@responses.activate
def test_scan_portals_null_name_falls_back_to_slug_for_careers_url(tmp_path):
    """name: null must not propagate to JobPosting.company (Pydantic rejects None).

    Reproducer for the T2-3 fallback defect: company.get("name", default)
    returns None when the key exists with a null value, so the default was
    never applied. The fetch then received company_name=None and the
    JobPosting model raised a ValidationError. The fallback must resolve to
    slug (or careers_url) instead.
    """
    responses.add(
        responses.GET,
        "https://example.com/careers",
        body="<html><body>Open roles</body></html>",
        status=200,
    )

    portals_path = _write_portals(
        tmp_path,
        [
            {
                "name": None,
                "domain": "example.com",
                "ats": None,
                "slug": "example",
                "careers_url": "https://example.com/careers",
                "active": True,
                "last_scanned": None,
                "last_had_openings": None,
            },
        ],
    )

    # Must not raise a Pydantic ValidationError; company falls back to slug.
    jobs = scan_portals(portals_path)

    assert len(jobs) == 1
    assert jobs[0].company == "example"
    assert jobs[0].source == "careers_url"


@responses.activate
def test_scan_portals_null_name_and_slug_falls_back_to_careers_url(tmp_path):
    """name: null and slug: null must fall back to careers_url, not None."""
    responses.add(
        responses.GET,
        "https://example.com/careers",
        body="<html><body>Open roles</body></html>",
        status=200,
    )

    portals_path = _write_portals(
        tmp_path,
        [
            {
                "name": None,
                "domain": "example.com",
                "ats": None,
                "slug": None,
                "careers_url": "https://example.com/careers",
                "active": True,
                "last_scanned": None,
                "last_had_openings": None,
            },
        ],
    )

    jobs = scan_portals(portals_path)

    assert len(jobs) == 1
    assert jobs[0].company == "https://example.com/careers"
    assert jobs[0].source == "careers_url"


# ---------------------------------------------------------------------------
# T2-5 / T3-4 — atomic, lock-aware, fail-soft write of portals.yml
# ---------------------------------------------------------------------------


@responses.activate
def test_scan_portals_fails_soft_on_permission_error(tmp_path, capsys):
    fixture_gh = json.loads((FIXTURES / "greenhouse_anthropic.json").read_text())
    responses.add(
        responses.GET,
        "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs",
        json=fixture_gh,
        status=200,
    )

    portals_path = _write_portals(
        tmp_path,
        [
            {
                "name": "Anthropic",
                "domain": "anthropic.com",
                "ats": "greenhouse",
                "slug": "anthropic",
                "active": True,
                "last_scanned": None,
                "last_had_openings": None,
            },
        ],
    )

    # Simulate an unwritable/locked portals.yml: the write must not crash.
    with patch(
        "board_aggregator.portal_scanner.atomic_write_text",
        side_effect=PermissionError(13, "Permission denied"),
    ):
        jobs = scan_portals(portals_path)

    # Scan results are still returned despite the write failure.
    assert len(jobs) >= 2
    out = capsys.readouterr().out
    assert "Could not save scan timestamps" in out


@responses.activate
def test_scan_portals_detects_file_lock(tmp_path, capsys):
    fixture_gh = json.loads((FIXTURES / "greenhouse_anthropic.json").read_text())
    responses.add(
        responses.GET,
        "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs",
        json=fixture_gh,
        status=200,
    )

    portals_path = _write_portals(
        tmp_path,
        [
            {
                "name": "Anthropic",
                "domain": "anthropic.com",
                "ats": "greenhouse",
                "slug": "anthropic",
                "active": True,
                "last_scanned": None,
                "last_had_openings": None,
            },
        ],
    )

    # atomic_write_text surfaces a lock as an OSError mentioning "locked".
    lock_exc = OSError(
        "File is locked (possibly open in an editor): portals.yml. "
        "Please close the file and try again."
    )
    with patch(
        "board_aggregator.portal_scanner.atomic_write_text",
        side_effect=lock_exc,
    ):
        jobs = scan_portals(portals_path)

    # Fail soft, and tell the user it's a lock (not a permissions problem).
    assert len(jobs) >= 2
    out = capsys.readouterr().out
    assert "locked" in out.lower()
    assert "editor" in out.lower()


@responses.activate
def test_scan_portals_uses_atomic_write(tmp_path):
    fixture_gh = json.loads((FIXTURES / "greenhouse_anthropic.json").read_text())
    responses.add(
        responses.GET,
        "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs",
        json=fixture_gh,
        status=200,
    )

    portals_path = _write_portals(
        tmp_path,
        [
            {
                "name": "Anthropic",
                "domain": "anthropic.com",
                "ats": "greenhouse",
                "slug": "anthropic",
                "active": True,
                "last_scanned": None,
                "last_had_openings": None,
            },
        ],
    )

    with patch(
        "board_aggregator.portal_scanner.atomic_write_text"
    ) as mock_write:
        scan_portals(portals_path)

    # The write goes through the atomic/lock-aware helper, not a bare write_text.
    assert mock_write.call_count == 1
    assert Path(mock_write.call_args.args[0]) == Path(portals_path)


# ---------------------------------------------------------------------------
# T3-3 — UTF-8 read of portals.yml (Spanish/accented content survives)
# ---------------------------------------------------------------------------


@responses.activate
def test_scan_portals_reads_utf8_portals(tmp_path):
    responses.add(
        responses.GET,
        "https://acentos.com/careers",
        body="<html><body>Vacantes</body></html>",
        status=200,
    )

    portals = {
        "config": {"scan_interval_days": 7, "disable_after_days": 30},
        "title_filter": {"positive": ["AI"], "negative": []},
        "companies": [
            {
                "name": "Compañía Española — Ingeniería",
                "domain": "acentos.com",
                "ats": None,
                "slug": None,
                "careers_url": "https://acentos.com/careers",
                "active": True,
                "last_scanned": None,
                "last_had_openings": None,
            },
        ],
    }
    path = tmp_path / "portals.yml"
    # Write non-ASCII content as UTF-8 (no ASCII escaping).
    path.write_text(
        yaml.dump(portals, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )

    # Must not raise a decode error and must preserve the accented name.
    jobs = scan_portals(str(path))

    assert len(jobs) == 1
    assert jobs[0].company == "Compañía Española — Ingeniería"
