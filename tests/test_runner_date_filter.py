from datetime import datetime, timedelta, timezone

from board_aggregator.models import JobPosting
from board_aggregator.runner import _filter_by_age, _parse_posting_date


def test_parse_iso_date():
    dt = _parse_posting_date("2025-06-15")
    assert dt is not None
    assert dt.year == 2025 and dt.month == 6 and dt.day == 15


def test_parse_iso_timestamp_z():
    dt = _parse_posting_date("2025-06-15T10:30:00Z")
    assert dt is not None
    assert dt.tzinfo is not None


def test_parse_rfc2822():
    dt = _parse_posting_date("Mon, 15 Jun 2025 10:30:00 +0000")
    assert dt is not None
    assert dt.year == 2025


def test_parse_bad_input_returns_none():
    assert _parse_posting_date("not a date") is None
    assert _parse_posting_date("") is None
    assert _parse_posting_date(None) is None
    assert _parse_posting_date("nan") is None


def test_filter_by_age_drops_old():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
    jobs = [
        JobPosting(title="Old", company="A", source="t", job_url="http://a", date_posted="2020-01-01"),
        JobPosting(title="Fresh", company="B", source="t", job_url="http://b", date_posted=recent),
        JobPosting(title="Undated", company="C", source="t", job_url="http://c", date_posted=None),
    ]

    kept = _filter_by_age(jobs, hours_old=24)

    titles = {j.title for j in kept}
    assert "Old" not in titles
    assert "Fresh" in titles
    assert "Undated" in titles


def test_filter_by_age_unparseable_kept():
    jobs = [
        JobPosting(title="Garbage Date", company="A", source="t", job_url="http://a", date_posted="who knows"),
    ]
    kept = _filter_by_age(jobs, hours_old=24)
    assert len(kept) == 1
