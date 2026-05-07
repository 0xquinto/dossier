import responses

from board_aggregator.scrapers.nocodejobs import LISTINGS_URL, NoCodeJobsScraper

NCJ_HTML = """
<html><body>
<ul class="job-list">
<li class="job-item featured"
    data-position="Bubble Developer - Contract"
    data-location="USA"
    data-team="Remote"
    data-description="No Code Jobs is seeking a Bubble Developer."
    data-category='["Bubble"]'
    data-salary="40">
  <a href="/jobs/bubble-developer-id-bd1">
    <span>Company</span><span>No Code Jobs</span>
    <span>Title and Location</span><span>Bubble Developer - Contract</span><span>05/17/2025</span>
    <span>Employment Type</span><span>FULL_TIME</span>
    <span>Salary</span><span>USD 40-45 per hour</span>
    <span>Team and Date</span><span>Remote</span><span>USA</span>
  </a>
</li>
<li class="job-item"
    data-position="WordPress Developer"
    data-location="USA"
    data-team="On-site"
    data-description="Warm Websites is hiring a WordPress Developer."
    data-category='["Wordpress"]'
    data-salary="22">
  <a href="https://example.com/external-apply">
    <span>Company</span><span>Warm Websites</span>
    <span>Title and Location</span><span>WordPress Developer</span><span>03/01/2026</span>
    <span>Employment Type</span><span>PART_TIME</span>
    <span>Salary</span><span>USD 22-30 per hour</span>
  </a>
</li>
<li class="job-item"
    data-position=""
    data-description="Should skip - no title">
  <a href="/jobs/x"><span>Company</span><span>Skipme</span></a>
</li>
</ul>
</body></html>
"""


@responses.activate
def test_nocodejobs_parses_jobs():
    responses.add(responses.GET, LISTINGS_URL, body=NCJ_HTML, status=200)

    jobs = NoCodeJobsScraper().scrape([])

    assert len(jobs) == 2

    bubble = jobs[0]
    assert bubble.company == "No Code Jobs"
    assert bubble.title == "Bubble Developer - Contract"
    assert bubble.source == "nocodejobs"
    assert bubble.job_url == "https://www.nocodejobs.org/jobs/bubble-developer-id-bd1"
    assert bubble.is_remote is True
    assert bubble.location == "USA"
    assert bubble.salary_min == 40
    assert bubble.salary_max == 45
    assert bubble.salary_interval == "hourly"
    assert bubble.salary_currency == "USD"
    assert bubble.job_type == "fulltime"
    assert bubble.date_posted == "2025-05-17"
    assert "Bubble" in (bubble.description or "")

    wp = jobs[1]
    assert wp.company == "Warm Websites"
    assert wp.is_remote is False
    assert wp.job_type == "parttime"
    assert wp.job_url == "https://example.com/external-apply"


@responses.activate
def test_nocodejobs_handles_listing_error():
    responses.add(responses.GET, LISTINGS_URL, body="", status=503)

    jobs = NoCodeJobsScraper().scrape([])
    assert jobs == []
