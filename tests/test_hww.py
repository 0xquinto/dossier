import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import responses
from click.testing import CliRunner

from board_aggregator.cli import main as cli_main
from board_aggregator.hww import README_URL, HWWIndex, enrich
from board_aggregator.models import JobPosting
from board_aggregator.runner import run_all

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "hww_readme_sample.md"
FIXTURE_TEXT = FIXTURE_PATH.read_text(encoding="utf-8")


# --- parsing ---------------------------------------------------------------


def test_parse_counts_companies():
    index = HWWIndex.parse(FIXTURE_TEXT)
    assert len(index.companies) == 6


def test_parse_full_entry():
    index = HWWIndex.parse(FIXTURE_TEXT)
    company = index.match("1000.software")
    assert company is not None
    assert company.url == "https://www.1000.software/careers"
    assert company.location == "Krakow, Poland / Remote"
    assert "take home" in company.process


def test_parse_entry_with_no_process_note():
    index = HWWIndex.parse(FIXTURE_TEXT)
    company = index.match("Abstract")
    assert company is not None
    assert company.location == "San Francisco, CA"
    assert company.process is None


def test_parse_entry_with_no_location():
    index = HWWIndex.parse(FIXTURE_TEXT)
    company = index.match("Zephyrio")
    assert company is not None
    assert company.location is None
    assert company.process is None


def test_parse_skips_non_entry_line():
    # The <!--lint disable--> line sits between Aalyria and Abstract in the
    # fixture; it must not be parsed as a company or break the entries around it.
    index = HWWIndex.parse(FIXTURE_TEXT)
    assert index.match("lint disable") is None
    assert index.match("Aalyria") is not None
    assert index.match("Abstract") is not None


def test_parse_stops_before_also_see():
    index = HWWIndex.parse(FIXTURE_TEXT)
    assert index.match("They Whiteboarded Me!") is None


# --- name normalization ------------------------------------------------


def test_match_is_case_insensitive():
    index = HWWIndex.parse(FIXTURE_TEXT)
    assert index.match("zapier") is not None
    assert index.match("ZAPIER") is not None
    assert index.match("Zapier") is not None


def test_match_ignores_punctuation_and_spacing():
    index = HWWIndex.parse(FIXTURE_TEXT)
    company = index.match("Zenefits (UI Team)")
    assert company is not None
    assert index.match("zenefits ui team") is company
    assert index.match("ZENEFITS-UI-TEAM") is company
    assert index.match("1000 Software") is index.match("1000.software")


def test_match_unknown_company_returns_none():
    index = HWWIndex.parse(FIXTURE_TEXT)
    assert index.match("Definitely Not Listed Inc") is None


# --- cache TTL ---------------------------------------------------------


def test_load_uses_fresh_cache_without_network(tmp_path):
    cache_path = tmp_path / "hww-readme.md"
    cache_path.write_text(FIXTURE_TEXT, encoding="utf-8")

    with patch("board_aggregator.hww.http_requests.get") as mock_get:
        index = HWWIndex.load(cache_path, max_age_days=7)

    mock_get.assert_not_called()
    assert index.match("Zapier") is not None


def test_load_absent_cache_fetches_and_writes(tmp_path):
    cache_path = tmp_path / "sub" / "hww-readme.md"

    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, README_URL, body=FIXTURE_TEXT, status=200)
        index = HWWIndex.load(cache_path)
        assert rsps.calls[0].request.url == README_URL

    assert cache_path.exists()
    assert cache_path.read_text(encoding="utf-8") == FIXTURE_TEXT
    assert index.match("Zapier") is not None


def test_load_stale_cache_triggers_refetch(tmp_path):
    cache_path = tmp_path / "hww-readme.md"
    cache_path.write_text("## A - C\n\n- [Old](https://old.example)\n", encoding="utf-8")
    old_time = time.time() - 8 * 86400
    import os

    os.utime(cache_path, (old_time, old_time))

    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, README_URL, body=FIXTURE_TEXT, status=200)
        index = HWWIndex.load(cache_path, max_age_days=7)

    assert index.match("Old") is None
    assert index.match("Zapier") is not None
    assert cache_path.read_text(encoding="utf-8") == FIXTURE_TEXT


# --- fetch-failure fallbacks --------------------------------------------


def test_load_fetch_failure_falls_back_to_stale_cache(tmp_path):
    cache_path = tmp_path / "hww-readme.md"
    cache_path.write_text(FIXTURE_TEXT, encoding="utf-8")
    old_time = time.time() - 30 * 86400
    import os

    os.utime(cache_path, (old_time, old_time))

    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, README_URL, body="boom", status=500)
        index = HWWIndex.load(cache_path, max_age_days=7)

    # Fetch failed, but the stale cache still parses.
    assert index.match("Zapier") is not None


def test_load_fetch_failure_no_cache_returns_empty_index(tmp_path):
    cache_path = tmp_path / "does-not-exist" / "hww-readme.md"

    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, README_URL, body="boom", status=500)
        index = HWWIndex.load(cache_path, max_age_days=7)

    assert index.companies == {}
    assert index.match("Zapier") is None


def test_load_never_raises_on_connection_error(tmp_path):
    cache_path = tmp_path / "hww-readme.md"

    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            README_URL,
            body=ConnectionError("network unreachable"),
        )
        index = HWWIndex.load(cache_path, max_age_days=7)  # must not raise

    assert index.companies == {}


# --- enrich() ------------------------------------------------------------


def _job(company: str) -> JobPosting:
    return JobPosting(
        title="AI Engineer",
        company=company,
        source="himalayas",
        job_url=f"https://example.com/{company}",
    )


def test_enrich_sets_fields_on_match():
    index = HWWIndex.parse(FIXTURE_TEXT)
    jobs = [_job("Zapier")]

    matched = enrich(jobs, index)

    assert matched == 1
    assert jobs[0].hww_listed is True
    assert jobs[0].hww_process == index.match("Zapier").process


def test_enrich_leaves_unmatched_jobs_untouched():
    index = HWWIndex.parse(FIXTURE_TEXT)
    jobs = [_job("Definitely Not Listed Inc")]

    matched = enrich(jobs, index)

    assert matched == 0
    assert jobs[0].hww_listed is False
    assert jobs[0].hww_process is None


def test_enrich_matched_entry_with_no_process_note_leaves_process_none():
    index = HWWIndex.parse(FIXTURE_TEXT)
    jobs = [_job("Abstract")]

    matched = enrich(jobs, index)

    assert matched == 1
    assert jobs[0].hww_listed is True
    assert jobs[0].hww_process is None


def test_enrich_returns_match_count_across_mixed_jobs():
    index = HWWIndex.parse(FIXTURE_TEXT)
    jobs = [_job("Zapier"), _job("Not Listed"), _job("Aalyria")]

    matched = enrich(jobs, index)

    assert matched == 2


# --- runner.run_all wiring ------------------------------------------------


def _one_scraper():
    mock_scraper = MagicMock()
    mock_scraper.name = "test_board"
    mock_scraper.scrape.return_value = [_job("Zapier")]
    return mock_scraper


def _mixed_scraper():
    mock_scraper = MagicMock()
    mock_scraper.name = "test_board"
    mock_scraper.scrape.return_value = [_job("Zapier"), _job("Not Listed")]
    return mock_scraper


def _unmatched_scraper():
    mock_scraper = MagicMock()
    mock_scraper.name = "test_board"
    mock_scraper.scrape.return_value = [_job("Definitely Not Listed Inc")]
    return mock_scraper


def test_run_all_enriches_by_default(tmp_path):
    with patch("board_aggregator.runner.get_all_scrapers", return_value=[_one_scraper()]), \
            patch("board_aggregator.hww.HWWIndex.load", return_value=HWWIndex.parse(FIXTURE_TEXT)):
        jobs = run_all(["query"], output_dir=tmp_path)

    assert jobs[0].hww_listed is True


def test_run_all_skips_hww_when_disabled(tmp_path):
    with patch("board_aggregator.runner.get_all_scrapers", return_value=[_one_scraper()]), \
            patch("board_aggregator.hww.HWWIndex.load") as mock_load:
        jobs = run_all(["query"], output_dir=tmp_path, hww=False)

    mock_load.assert_not_called()
    assert jobs[0].hww_listed is False


# --- runner.run_all hww_only restrict mode ---------------------------------


def test_run_all_hww_only_keeps_matches_and_prints_count(tmp_path, capsys):
    with patch("board_aggregator.runner.get_all_scrapers", return_value=[_mixed_scraper()]), \
            patch("board_aggregator.hww.HWWIndex.load", return_value=HWWIndex.parse(FIXTURE_TEXT)):
        jobs = run_all(["query"], output_dir=tmp_path, hww_only=True)

    assert [job.company for job in jobs] == ["Zapier"]
    assert "[runner] HWW-only filter: 1/2 postings kept" in capsys.readouterr().out


def test_run_all_hww_only_requires_hww(tmp_path):
    with pytest.raises(ValueError):
        run_all(["query"], output_dir=tmp_path, hww=False, hww_only=True)


def test_run_all_hww_only_empty_match_writes_valid_outputs(tmp_path):
    with patch("board_aggregator.runner.get_all_scrapers", return_value=[_unmatched_scraper()]), \
            patch("board_aggregator.hww.HWWIndex.load", return_value=HWWIndex.parse(FIXTURE_TEXT)):
        jobs = run_all(["query"], output_dir=tmp_path, hww_only=True)

    assert jobs == []
    assert json.loads((tmp_path / "all-postings-index.json").read_text()) == []
    assert (tmp_path / "all-postings.csv").exists()
    assert (tmp_path / "all-postings.md").exists()


# --- cli --no-hww wiring ---------------------------------------------------


def test_cli_no_hww_flag_disables_enrichment():
    with patch("board_aggregator.cli.run_all", return_value=[]) as mock_run_all:
        result = CliRunner().invoke(cli_main, ["--no-hww"])

    assert result.exit_code == 0, result.output
    assert mock_run_all.call_args.kwargs["hww"] is False


def test_cli_hww_enabled_by_default():
    with patch("board_aggregator.cli.run_all", return_value=[]) as mock_run_all:
        result = CliRunner().invoke(cli_main, [])

    assert result.exit_code == 0, result.output
    assert mock_run_all.call_args.kwargs["hww"] is True


# --- cli --hww-only wiring ---------------------------------------------------


def test_cli_hww_only_flag_wires_to_run_all():
    with patch("board_aggregator.cli.run_all", return_value=[]) as mock_run_all:
        result = CliRunner().invoke(cli_main, ["--hww-only"])

    assert result.exit_code == 0, result.output
    assert mock_run_all.call_args.kwargs["hww_only"] is True


def test_cli_hww_only_disabled_by_default():
    with patch("board_aggregator.cli.run_all", return_value=[]) as mock_run_all:
        result = CliRunner().invoke(cli_main, [])

    assert result.exit_code == 0, result.output
    assert mock_run_all.call_args.kwargs["hww_only"] is False


def test_cli_hww_only_conflicts_with_no_hww():
    result = CliRunner().invoke(cli_main, ["--hww-only", "--no-hww"])

    assert result.exit_code != 0
    assert "--hww-only requires --hww" in result.output
