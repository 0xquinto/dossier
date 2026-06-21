from board_aggregator.models import JobPosting


def test_job_posting_minimal():
    job = JobPosting(
        title="AI Engineer",
        company="Acme Corp",
        source="himalayas",
        job_url="https://example.com/job/1",
    )
    assert job.title == "AI Engineer"
    assert job.company == "Acme Corp"
    assert job.source == "himalayas"
    assert job.salary_min is None
    assert job.salary_max is None
    assert job.is_remote is True  # default


def test_job_posting_full():
    job = JobPosting(
        title="Operations Manager",
        company="Grafana Labs",
        source="indeed",
        job_url="https://indeed.com/viewjob?jk=abc123",
        location="Remote, US",
        is_remote=True,
        salary_min=150000,
        salary_max=200000,
        salary_currency="USD",
        salary_interval="yearly",
        date_posted="2026-03-27",
        job_type="fulltime",
        description="Lead AI operations...",
    )
    assert job.salary_min == 150000
    assert job.salary_currency == "USD"
    assert job.date_posted == "2026-03-27"


def test_job_posting_dedup_key():
    job = JobPosting(
        title="AI Engineer",
        company="Acme Corp",
        source="himalayas",
        job_url="https://example.com/job/1",
    )
    key = job.dedup_key
    assert key == ("ai engineer", "acme corp")


def test_job_posting_dedup_key_normalizes():
    job1 = JobPosting(title="AI Engineer ", company="  Acme Corp", source="a", job_url="https://x.com/1")
    job2 = JobPosting(title="ai engineer", company="acme corp", source="b", job_url="https://x.com/2")
    assert job1.dedup_key == job2.dedup_key


def test_job_posting_rejects_invalid_url():
    import pytest
    from pydantic import ValidationError

    for bad in ["", "   ", "not a url", "viewjob?jk=abc", "/relative/path"]:
        with pytest.raises(ValidationError):
            JobPosting(
                title="AI Engineer",
                company="Acme Corp",
                source="himalayas",
                job_url=bad,
            )


def test_job_posting_rejects_non_http_schemes():
    # Only http(s) URLs are allowed: non-web schemes (a fabricated/unsafe link
    # risk) must be rejected even though AnyUrl parses them. A Windows path like
    # C:\... parses with scheme "c", so it is rejected by the same gate.
    import pytest
    from pydantic import ValidationError

    for bad in [
        "javascript:alert(1)",
        "data:text/html,<h1>x</h1>",
        "mailto:hr@example.com",
        "tel:+15551234567",
        "ftp://example.com/file",
        "about:blank",
        r"C:\Users\me\job.html",
    ]:
        with pytest.raises(ValidationError):
            JobPosting(
                title="AI Engineer",
                company="Acme Corp",
                source="himalayas",
                job_url=bad,
            )


def test_job_posting_url_preserved_byte_for_byte():
    # A valid URL must survive validation unchanged (no normalization such as
    # an appended trailing slash) so scraped/portal links stay exact.
    for url in [
        "https://example.com",
        "https://indeed.com/viewjob?jk=abc123",
        "https://example.com/job/1",
        "http://foo.com/a/b?c=d#e",
    ]:
        job = JobPosting(
            title="AI Engineer",
            company="Acme Corp",
            source="himalayas",
            job_url=url,
        )
        assert job.job_url == url


def test_job_posting_application_deadline_optional():
    # Optional, defaults to None so urgency language can be gated on its presence.
    job = JobPosting(
        title="Governance Officer",
        company="IUCN",
        source="himalayas",
        job_url="https://example.com/job/1",
    )
    assert job.application_deadline is None

    dated = JobPosting(
        title="Governance Officer",
        company="IUCN",
        source="himalayas",
        job_url="https://example.com/job/1",
        application_deadline="2026-06-19",
    )
    assert dated.application_deadline == "2026-06-19"


def test_job_posting_rejects_free_text_deadline():
    # Free-text deadlines ("TOMORROW", "ASAP", "") are a fabrication risk and
    # must be rejected at the model layer so no agent can smuggle urgency framing
    # through the deadline field. Only ISO dates (or None) are accepted.
    import pytest
    from pydantic import ValidationError

    # Impossible calendar dates that pass a YYYY-MM-DD shape check ("2026-13-99",
    # month 13 / day 99; "2026-02-30", no Feb 30) must also be rejected — the
    # validator proves a real date via date.fromisoformat, not just the shape.
    for bad in [
        "TOMORROW",
        "closes soon",
        "ASAP",
        "",
        "  ",
        "2026/06/19",
        "June 19",
        "06-19-2026",
        "2026-13-99",
        "2026-02-30",
        "2026-00-10",
        "2026-06-00",
    ]:
        with pytest.raises(ValidationError):
            JobPosting(
                title="AI Engineer",
                company="Acme Corp",
                source="himalayas",
                job_url="https://example.com/job/1",
                application_deadline=bad,
            )


def test_has_verified_deadline_gate():
    # The model exposes a gate so urgency framing can be conditioned on a real,
    # source-retrieved deadline. Unverified (None) postings report False.
    unverified = JobPosting(
        title="AI Engineer",
        company="Acme Corp",
        source="himalayas",
        job_url="https://example.com/job/1",
    )
    assert unverified.application_deadline is None
    assert unverified.has_verified_deadline is False

    verified = JobPosting(
        title="AI Engineer",
        company="Acme Corp",
        source="himalayas",
        job_url="https://example.com/job/1",
        application_deadline="2026-06-19",
    )
    assert verified.has_verified_deadline is True


def test_job_url_mutation_revalidates():
    # The post-creation mutation bypass is closed: reassigning job_url after
    # construction re-runs the URL validator, so a validated link cannot be
    # overwritten with an empty/fabricated value.
    import pytest
    from pydantic import ValidationError

    job = JobPosting(
        title="AI Engineer",
        company="Acme Corp",
        source="himalayas",
        job_url="https://example.com/job/1",
    )
    for bad in ["", "not a url", "/relative"]:
        with pytest.raises(ValidationError):
            job.job_url = bad
    # job_url is unchanged after the rejected assignments.
    assert job.job_url == "https://example.com/job/1"

    # A valid reassignment is accepted and preserved byte-for-byte.
    job.job_url = "https://example.com/job/2"
    assert job.job_url == "https://example.com/job/2"


def test_deadline_mutation_revalidates():
    # Reassigning application_deadline also re-runs its validator, blocking a
    # fabricated free-text deadline from being injected post-construction.
    import pytest
    from pydantic import ValidationError

    job = JobPosting(
        title="AI Engineer",
        company="Acme Corp",
        source="himalayas",
        job_url="https://example.com/job/1",
    )
    with pytest.raises(ValidationError):
        job.application_deadline = "TOMORROW"
    assert job.application_deadline is None
    assert job.has_verified_deadline is False


def test_try_create_skips_invalid_without_raising():
    # Scrapers with empty-URL fallback paths use try_create to skip unverified
    # postings gracefully instead of crashing the whole scrape with a
    # ValidationError. Invalid input returns None; valid input returns a model.
    assert (
        JobPosting.try_create(
            title="AI Engineer",
            company="Acme Corp",
            source="cryptojobslist",
            job_url="",  # empty fallback when seo_slug missing
        )
        is None
    )
    assert (
        JobPosting.try_create(
            title="AI Engineer",
            company="Acme Corp",
            source="reddit_jobs",
            job_url="https://reddit.com/r/forhire/comments/abc",
        )
        is not None
    )


# --- Task 2: Base class tests ---

from board_aggregator.scrapers.base import BaseScraper


def test_base_scraper_is_abstract():
    import pytest

    with pytest.raises(TypeError):
        BaseScraper()


class DummyScraper(BaseScraper):
    name = "dummy"

    def scrape(self, queries, is_remote=True):
        return [
            JobPosting(
                title="Test Job",
                company="Test Co",
                source=self.name,
                job_url="https://example.com/1",
            )
        ]


def test_dummy_scraper_works():
    s = DummyScraper()
    results = s.scrape(["test query"])
    assert len(results) == 1
    assert results[0].source == "dummy"
