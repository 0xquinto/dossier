from unittest.mock import MagicMock, patch

import pytest

from board_aggregator.models import JobPosting
from board_aggregator.runner import collect_from_boards, deduplicate, run_all


def test_deduplicate_by_title_company():
    jobs = [
        JobPosting(title="AI Engineer", company="Acme", source="indeed", job_url="https://a.com/1"),
        JobPosting(title="AI Engineer", company="Acme", source="himalayas", job_url="https://b.com/2"),
        JobPosting(title="Rust Dev", company="NXLog", source="indeed", job_url="https://c.com/3"),
    ]

    result = deduplicate(jobs)

    assert len(result) == 2
    titles = {j.title for j in result}
    assert "AI Engineer" in titles
    assert "Rust Dev" in titles


def test_deduplicate_keeps_version_with_salary():
    jobs = [
        JobPosting(title="AI Engineer", company="Acme", source="indeed", job_url="https://a.com/1"),
        JobPosting(title="AI Engineer", company="Acme", source="himalayas", job_url="https://b.com/2", salary_min=150000, salary_max=200000),
    ]

    result = deduplicate(jobs)

    assert len(result) == 1
    assert result[0].salary_min == 150000  # kept the richer version


def test_deduplicate_keeps_version_with_description():
    jobs = [
        JobPosting(title="AI Engineer", company="Acme", source="a", job_url="https://a.com/1", description="Full description here..."),
        JobPosting(title="AI Engineer", company="Acme", source="b", job_url="https://b.com/2"),
    ]

    result = deduplicate(jobs)

    assert len(result) == 1
    assert result[0].description == "Full description here..."


def test_collect_from_boards_returns_raw_jobs():
    mock_scraper = MagicMock()
    mock_scraper.name = "test_board"
    mock_scraper.scrape.return_value = [
        JobPosting(
            title="AI Eng", company="TestCo", source="test_board", job_url="http://a"
        ),
    ]

    with patch("board_aggregator.runner.get_all_scrapers", return_value=[mock_scraper]):
        jobs = collect_from_boards(["query"], is_remote=True)

    assert len(jobs) == 1
    assert jobs[0].title == "AI Eng"


def test_collect_empty_scrapers_runs_zero_boards():
    # C2: an explicit empty list means "run zero boards", not "run all". The
    # gate is `scrapers is not None`, so [] must skip every scraper.
    mock_scraper = MagicMock()
    mock_scraper.name = "test_board"
    mock_scraper.scrape.return_value = [
        JobPosting(title="X", company="Y", source="test_board", job_url="http://a"),
    ]

    with patch("board_aggregator.runner.get_all_scrapers", return_value=[mock_scraper]):
        jobs = collect_from_boards(["query"], is_remote=True, scrapers=[])

    assert jobs == []
    mock_scraper.scrape.assert_not_called()


def test_collect_none_scrapers_runs_all_boards():
    # None (no filter) is the "run everything" sentinel — must still run boards.
    mock_scraper = MagicMock()
    mock_scraper.name = "test_board"
    mock_scraper.scrape.return_value = [
        JobPosting(title="X", company="Y", source="test_board", job_url="http://a"),
    ]

    with patch("board_aggregator.runner.get_all_scrapers", return_value=[mock_scraper]):
        jobs = collect_from_boards(["query"], is_remote=True, scrapers=None)

    assert len(jobs) == 1
    mock_scraper.scrape.assert_called_once()


def _one_scraper():
    mock_scraper = MagicMock()
    mock_scraper.name = "test_board"
    mock_scraper.scrape.return_value = [
        JobPosting(title="AI Eng", company="TestCo", source="test_board", job_url="http://a"),
    ]
    return mock_scraper


def test_run_all_writes_outputs(tmp_path):
    with patch("board_aggregator.runner.get_all_scrapers", return_value=[_one_scraper()]):
        run_all(["query"], output_dir=tmp_path)

    assert (tmp_path / "all-postings.csv").exists()
    assert (tmp_path / "all-postings.md").exists()
    assert (tmp_path / "all-postings-index.json").exists()  # T2-7 compact index


def test_run_all_is_write_once(tmp_path):
    """A second run_all into the same dir must fail, not silently clobber (T1-4)."""
    with patch("board_aggregator.runner.get_all_scrapers", return_value=[_one_scraper()]):
        run_all(["query"], output_dir=tmp_path)
        with pytest.raises(FileExistsError):
            run_all(["query"], output_dir=tmp_path)
