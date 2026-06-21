"""Tests for the per-user board allow/deny filter (T2-6) and the 80000hours
wiring check (T2-2)."""

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from board_aggregator.cli import load_board_filter, main
from board_aggregator.scrapers import filter_scrapers

CRYPTO_BOARDS = ["crypto_jobs", "cryptojobslist", "cryptocurrencyjobs", "web3career"]


# --- filter_scrapers (pure helper) ---------------------------------------


def test_filter_no_config_returns_everything_unchanged():
    names = ["a", "b", "c"]
    assert filter_scrapers(names) == names
    assert filter_scrapers(names, None, None) == names


def test_filter_denylist_drops_named_boards():
    names = ["80000hours", "himalayas", "crypto_jobs", "web3career", "reddit"]
    result = filter_scrapers(names, denylist=["crypto_jobs", "web3career"])
    assert result == ["80000hours", "himalayas", "reddit"]


def test_filter_allowlist_restricts_to_named_boards():
    names = ["80000hours", "himalayas", "crypto_jobs", "reddit"]
    result = filter_scrapers(names, allowlist=["80000hours", "reddit"])
    assert result == ["80000hours", "reddit"]


def test_filter_allow_then_deny_compose():
    names = ["a", "b", "c", "d"]
    result = filter_scrapers(names, allowlist=["a", "b", "c"], denylist=["b"])
    assert result == ["a", "c"]


def test_filter_preserves_order():
    names = ["c", "a", "b"]
    assert filter_scrapers(names, denylist=["a"]) == ["c", "b"]


# --- T2-6 bypass: malformed (non-list) allow/deny must not silently bypass ---


def test_filter_string_denylist_rejected_not_char_iterated():
    # The bypass: 'crypto_jobs cryptojobslist' as a bare string would become a
    # set of characters, matching no board and leaking everything through.
    names = ["crypto_jobs", "cryptojobslist", "80000hours", "himalayas"]
    with pytest.raises(ValueError):
        filter_scrapers(names, denylist="crypto_jobs cryptojobslist")


def test_filter_string_allowlist_rejected():
    names = ["crypto_jobs", "80000hours"]
    with pytest.raises(ValueError):
        filter_scrapers(names, allowlist="80000hours")


def test_filter_nonlist_type_rejected():
    names = ["a", "b"]
    with pytest.raises(ValueError):
        filter_scrapers(names, denylist=42)
    with pytest.raises(ValueError):
        filter_scrapers(names, allowlist={"a": 1})


def test_list_scrapers_malformed_deny_fails_no_leak(tmp_path):
    # Realistic accident: list dashes forgotten, deny is a single string.
    p = tmp_path / "portals.yml"
    p.write_text("boards:\n  deny: crypto_jobs cryptojobslist\n")
    result = _list_scrapers(["--list-scrapers", "-p", str(p)])
    # Must fail loudly rather than running every board.
    assert result.exit_code != 0
    # And must NOT have produced a scraper listing (which would mean the deny
    # filter was bypassed and every board leaked through).
    assert "Available scrapers:" not in result.output


# --- load_board_filter (portals.yml reader) ------------------------------


def test_load_board_filter_no_path_defaults_to_all():
    assert load_board_filter(None) == (None, None)


def test_load_board_filter_missing_boards_section(tmp_path):
    p = tmp_path / "portals.yml"
    p.write_text("config:\n  scan_interval_days: 7\ncompanies: []\n")
    assert load_board_filter(str(p)) == (None, None)


def test_load_board_filter_reads_denylist(tmp_path):
    p = tmp_path / "portals.yml"
    p.write_text(
        "boards:\n"
        "  deny:\n"
        "    - crypto_jobs\n"
        "    - cryptojobslist\n"
        "    - cryptocurrencyjobs\n"
        "    - web3career\n"
    )
    allow, deny = load_board_filter(str(p))
    assert allow is None
    assert deny == CRYPTO_BOARDS


def test_load_board_filter_reads_allowlist(tmp_path):
    p = tmp_path / "portals.yml"
    p.write_text("boards:\n  allow:\n    - 80000hours\n    - himalayas\n")
    allow, deny = load_board_filter(str(p))
    assert allow == ["80000hours", "himalayas"]
    assert deny is None


# --- end-to-end via --list-scrapers --------------------------------------


def _list_scrapers(args):
    return CliRunner().invoke(main, args)


def test_list_scrapers_default_shows_all_boards():
    result = _list_scrapers(["--list-scrapers"])
    assert result.exit_code == 0
    # T2-2: 80000hours must be wired and visible by default.
    assert "80000hours" in result.output
    for board in CRYPTO_BOARDS:
        assert board in result.output


def test_list_scrapers_denylist_excludes_crypto(tmp_path):
    p = tmp_path / "portals.yml"
    p.write_text(
        "boards:\n  deny:\n"
        + "".join(f"    - {b}\n" for b in CRYPTO_BOARDS)
    )
    result = _list_scrapers(["--list-scrapers", "-p", str(p)])
    assert result.exit_code == 0
    # All 4 crypto boards filtered out...
    for board in CRYPTO_BOARDS:
        assert board not in result.output
    # ...while on-profile boards (incl. 80000hours) remain.
    assert "80000hours" in result.output
    assert "himalayas" in result.output


def test_list_scrapers_allowlist_restricts(tmp_path):
    p = tmp_path / "portals.yml"
    p.write_text("boards:\n  allow:\n    - 80000hours\n    - himalayas\n")
    result = _list_scrapers(["--list-scrapers", "-p", str(p)])
    assert result.exit_code == 0
    lines = [ln.strip("- ").strip() for ln in result.output.splitlines() if ln.startswith("  - ")]
    assert sorted(lines) == ["80000hours", "himalayas"]


# --- C3: the run path (which boards actually run) -------------------------
# Every test above stops at --list-scrapers, which returns before run_all is
# reached. These patch run_all and assert the `scrapers` kwarg it receives, so
# the precedence/intersection logic deciding which boards run is guarded.


def _all_registered_boards():
    """Force scraper registration (the CLI does this via imports inside main)
    and return every registered board name."""
    CliRunner().invoke(main, ["--list-scrapers"])
    from board_aggregator.scrapers import SCRAPER_REGISTRY

    return list(SCRAPER_REGISTRY.keys())


def _run_scrapers_kwarg(args):
    """Invoke main on the run path (no --list-scrapers) with run_all mocked;
    return the `scrapers` kwarg run_all was called with."""
    with patch("board_aggregator.cli.run_all", return_value=[]) as mock_run_all:
        result = CliRunner().invoke(main, args)
    assert result.exit_code == 0, result.output
    mock_run_all.assert_called_once()
    return mock_run_all.call_args.kwargs["scrapers"]


def test_run_portals_deny_excludes_those_boards(tmp_path):
    p = tmp_path / "portals.yml"
    p.write_text(
        "boards:\n  deny:\n"
        + "".join(f"    - {b}\n" for b in CRYPTO_BOARDS)
    )
    scrapers = _run_scrapers_kwarg(["-p", str(p)])
    assert scrapers is not None
    for board in CRYPTO_BOARDS:
        assert board not in scrapers
    assert "80000hours" in scrapers


def test_run_explicit_scraper_passes_through():
    scrapers = _run_scrapers_kwarg(["-s", "himalayas"])
    assert scrapers == ["himalayas"]


def test_run_explicit_denied_scraper_errors_no_leak(tmp_path):
    # C2 lock: -s of an all-denied board must NOT run every board. The CLI now
    # refuses with a non-zero exit instead of passing an empty list that the
    # runner would (pre-fix) treat as "run all".
    p = tmp_path / "portals.yml"
    p.write_text("boards:\n  deny:\n    - himalayas\n")
    with patch("board_aggregator.cli.run_all", return_value=[]) as mock_run_all:
        result = CliRunner().invoke(main, ["-s", "himalayas", "-p", str(p)])
    assert result.exit_code != 0
    # Must not have reached the run with an empty (=> all-boards) filter.
    mock_run_all.assert_not_called()


def test_run_no_filter_passes_none():
    scrapers = _run_scrapers_kwarg([])
    assert scrapers is None


def test_run_portals_deny_all_boards_errors_no_silent_noop(tmp_path):
    # GA bypass: with NO -s flag, a portals.yml deny-list covering every
    # available board left scraper_filter == enabled == []. That empty list
    # reached run_all (now meaning "run zero boards" under C2), so the CLI
    # silently scraped nothing. It must refuse with a non-zero exit instead.
    # The CLI registers scrapers via imports inside main(); list them the same
    # way so the deny-list actually covers every board the CLI will see.
    all_boards = sorted(_all_registered_boards())
    assert all_boards, "registry should be populated"
    p = tmp_path / "portals.yml"
    p.write_text("boards:\n  deny:\n" + "".join(f"    - {b}\n" for b in all_boards))
    with patch("board_aggregator.cli.run_all", return_value=[]) as mock_run_all:
        result = CliRunner().invoke(main, ["-p", str(p)])
    assert result.exit_code != 0
    # Must not have reached the run with an empty (=> zero-boards) filter.
    mock_run_all.assert_not_called()


def test_run_portals_allow_unknown_board_errors_no_silent_noop(tmp_path):
    # Same bypass via an allowlist that matches no available board: the
    # intersection is empty, so without -s the CLI would pass [] to run_all
    # and scrape nothing. Refuse instead.
    p = tmp_path / "portals.yml"
    p.write_text("boards:\n  allow:\n    - not_a_real_board\n")
    with patch("board_aggregator.cli.run_all", return_value=[]) as mock_run_all:
        result = CliRunner().invoke(main, ["-p", str(p)])
    assert result.exit_code != 0
    mock_run_all.assert_not_called()


def test_run_file_exists_error_is_clean_not_traceback():
    # Write-once guard tripped: cli.main catches FileExistsError and re-raises
    # as ClickException so the guidance shows without a traceback.
    msg = "Refusing to overwrite existing file: x. Use a fresh run directory."
    with patch(
        "board_aggregator.cli.run_all", side_effect=FileExistsError(msg)
    ):
        result = CliRunner().invoke(main, [])
    assert result.exit_code != 0
    assert msg in result.output
    # ClickException prints a one-line "Error: ..."; no traceback leaked.
    assert "Traceback" not in result.output
    assert result.exc_info is None or result.exc_info[0] is SystemExit


def test_run_lock_oserror_is_clean_not_traceback():
    # IMP-1: a locked output file (e.g. all-postings.csv open in Excel) makes
    # atomic_write_text exhaust retries and raise a bare OSError. cli.main now
    # catches OSError and surfaces the (already user-ready) message cleanly.
    msg = "File is locked: all-postings.csv. Close the file and try again."
    with patch("board_aggregator.cli.run_all", side_effect=OSError(msg)):
        result = CliRunner().invoke(main, [])
    assert result.exit_code != 0
    assert msg in result.output
    assert "Traceback" not in result.output


def test_malformed_portals_yaml_is_clean_not_traceback(tmp_path):
    # IMP-2: a syntactically broken / non-mapping portals.yml must produce a
    # clean ClickException, not a raw YAMLError/AttributeError traceback.
    p = tmp_path / "portals.yml"
    p.write_text("- this is a bare list, not a mapping\n")
    result = CliRunner().invoke(main, ["-p", str(p)])
    assert result.exit_code != 0
    assert "not a valid portals file" in result.output
    assert "Traceback" not in result.output


def test_unparseable_portals_yaml_is_clean_not_traceback(tmp_path):
    p = tmp_path / "portals.yml"
    p.write_text("boards: [unclosed\n")  # invalid YAML
    result = CliRunner().invoke(main, ["-p", str(p)])
    assert result.exit_code != 0
    assert "Could not parse" in result.output
    assert "Traceback" not in result.output


# --- T2-2 static check: 80000hours is registered and wired in the CLI ----


def test_80000hours_registered_and_imported_in_cli():
    from board_aggregator.cli import main as _cli_main  # noqa: F401

    cli_src = Path(__file__).resolve().parent.parent / "board_aggregator" / "cli.py"
    text = cli_src.read_text()
    assert "import board_aggregator.scrapers.eighty_thousand_hours" in text

    result = _list_scrapers(["--list-scrapers"])
    assert "  - 80000hours" in result.output
