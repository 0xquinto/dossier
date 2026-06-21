import csv
import errno
import json
from unittest.mock import patch

import pytest

from board_aggregator.models import JobPosting
from board_aggregator.output import (
    write_compact_index,
    write_csv,
    write_markdown,
)


SAMPLE_JOBS = [
    JobPosting(
        title="AI Engineer",
        company="Grafana Labs",
        source="indeed",
        job_url="https://indeed.com/viewjob?jk=abc",
        location="Remote, US",
        salary_min=154000,
        salary_max=185000,
        date_posted="2026-03-27",
        job_type="fulltime",
        description="Build AI/ML ops tooling...",
    ),
    JobPosting(
        title="Rust Developer",
        company="NXLog",
        source="himalayas",
        job_url="https://himalayas.app/jobs/rust-dev",
        location="Remote",
    ),
]


def test_write_csv(tmp_path):
    path = tmp_path / "out.csv"

    write_csv(SAMPLE_JOBS, path)

    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 2
    assert rows[0]["title"] == "AI Engineer"
    assert rows[0]["company"] == "Grafana Labs"
    assert rows[0]["salary_min"] == "154000"
    assert rows[1]["salary_min"] == ""


def test_write_markdown(tmp_path):
    path = tmp_path / "out.md"

    write_markdown(SAMPLE_JOBS, path)

    content = path.read_text(encoding="utf-8")
    assert "# Phase 1: Job Board Scrape Results" in content
    assert "## AI Engineer" in content
    assert "Grafana Labs" in content
    assert "$154,000 - $185,000" in content or "154000" in content
    assert "## Rust Developer" in content


# --- T2-1 / T3-3: UTF-8 encoding ---

UTF8_JOBS = [
    JobPosting(
        title="Ingeniero de Soluciones 🚀",
        company="Innovadores café",
        source="indeed",
        job_url="https://example.com/1",
        location="Ciudad de México, España",
        description="Equipo dinámico ♻️ — Résumé con acentos: á, é, í, ó, ú, ñ 😊",
    ),
]


def test_write_utf8_content_to_csv_and_markdown(tmp_path):
    csv_path = tmp_path / "utf8.csv"
    md_path = tmp_path / "utf8.md"

    write_csv(UTF8_JOBS, csv_path)
    write_markdown(UTF8_JOBS, md_path)

    csv_text = csv_path.read_text(encoding="utf-8")
    md_text = md_path.read_text(encoding="utf-8")

    for needle in ["🚀", "café", "Innovadores", "♻️", "Résumé", "ñ", "México", "España", "😊"]:
        assert needle in csv_text, f"missing {needle!r} in CSV"
        assert needle in md_text, f"missing {needle!r} in markdown"


def test_encoding_unicode_output(tmp_path):
    """Spanish/accented characters survive round-trip (no cp1252 mojibake)."""
    jobs = [
        JobPosting(
            title="Ingeniero",
            company="Compañía Española",
            source="indeed",
            job_url="https://example.com/es",
            location="Cataluña",
            description="Pingüino mañana — á é í ó ú ñ",
        ),
    ]
    csv_path = tmp_path / "es.csv"
    md_path = tmp_path / "es.md"

    write_csv(jobs, csv_path)
    write_markdown(jobs, md_path)

    csv_text = csv_path.read_text(encoding="utf-8")
    md_text = md_path.read_text(encoding="utf-8")

    assert "Compañía Española" in csv_text
    assert "Cataluña" in csv_text
    assert "Pingüino mañana" in csv_text
    assert "Compañía Española" in md_text
    assert "Cataluña" in md_text
    assert "�" not in csv_text  # no replacement char (mojibake marker)
    assert "�" not in md_text


# --- T1-4: write-once semantics ---

def test_write_csv_refuses_to_overwrite(tmp_path):
    path = tmp_path / "once.csv"
    write_csv(SAMPLE_JOBS, path)
    with pytest.raises(FileExistsError):
        write_csv(SAMPLE_JOBS, path)


def test_write_markdown_refuses_to_overwrite(tmp_path):
    path = tmp_path / "once.md"
    write_markdown(SAMPLE_JOBS, path)
    with pytest.raises(FileExistsError):
        write_markdown(SAMPLE_JOBS, path)


def test_write_overwrite_flag_allows_replace(tmp_path):
    path = tmp_path / "again.csv"
    write_csv(SAMPLE_JOBS, path)
    write_csv(SAMPLE_JOBS, path, overwrite=True)  # must not raise


# --- T2-7: compact JSON index ---

def _make_jobs(n: int) -> list[JobPosting]:
    return [
        JobPosting(
            title=f"AI Engineer {i}",
            company=f"Company {i}",
            source="indeed",
            job_url=f"https://example.com/job/{i}",
            location="Remote",
            salary_min=120000 + i,
            salary_max=160000 + i,
            date_posted="2026-03-27",
            job_type="fulltime",
            # Realistic full-length JD: markdown truncates to 300 chars, the
            # compact index drops it entirely — this is what drives the gap.
            description="Build and operate AI/ML platform tooling. " * 30,
        )
        for i in range(n)
    ]


def test_write_compact_index(tmp_path):
    jobs = _make_jobs(900)
    index_path = tmp_path / "all-postings-index.json"
    md_path = tmp_path / "all-postings.md"

    write_compact_index(jobs, index_path)
    write_markdown(jobs, md_path)

    assert index_path.exists()

    records = json.loads(index_path.read_text(encoding="utf-8"))
    assert len(records) == len(jobs)
    # Round-trip: minimal fields present and correct.
    assert records[0]["title"] == "AI Engineer 0"
    assert records[0]["company"] == "Company 0"
    assert records[0]["salary_min"] == 120000
    assert set(records[0].keys()) == {
        "title", "company", "salary_min", "salary_max",
        "source", "job_url", "is_remote", "location", "application_deadline",
    }
    # location + application_deadline are present so ranker-7 can score
    # location-fit and deadline-urgency from the index alone (I3).
    assert records[0]["location"] == "Remote"
    assert records[0]["application_deadline"] is None

    # Compact: index is substantially smaller than the human markdown
    # (markdown truncates descriptions to 300 chars, so the gap is capped,
    # but the index omits descriptions entirely and stays tiny per record).
    # The index now also carries location + application_deadline (I3), so the
    # ratio is tighter than before, but markdown is still the larger artifact.
    assert index_path.stat().st_size < md_path.stat().st_size
    assert md_path.stat().st_size > 2 * index_path.stat().st_size
    assert index_path.stat().st_size / len(jobs) < 250  # bytes per record


def test_write_compact_index_refuses_to_overwrite(tmp_path):
    path = tmp_path / "idx.json"
    write_compact_index(SAMPLE_JOBS, path)
    with pytest.raises(FileExistsError):
        write_compact_index(SAMPLE_JOBS, path)


# --- T3-2: write_csv is lock-aware (file open in an editor) ---

def test_write_csv_retries_on_lock_then_succeeds(tmp_path):
    """EBUSY on the first 2 attempts, success on the 3rd — CSV path must
    route through the lock-aware atomic writer, not a raw open()."""
    path = tmp_path / "locked.csv"
    real_replace = __import__("os").replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise OSError(errno.EBUSY, "Resource busy")
        return real_replace(src, dst)

    with patch("board_aggregator.file_utils.os.replace", side_effect=flaky_replace), \
            patch("board_aggregator.file_utils.time.sleep"):
        write_csv(SAMPLE_JOBS, path)  # must not crash with unhandled OSError

    assert calls["n"] == 3  # retried twice, succeeded on third
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert rows[0]["title"] == "AI Engineer"


def test_write_csv_raises_friendly_message_after_retries(tmp_path):
    """When all-postings.csv stays locked, write_csv surfaces a 'close the
    file' message instead of leaking the raw EBUSY errno (T3-2)."""
    path = tmp_path / "stuck.csv"

    def always_busy(src, dst):
        raise OSError(errno.EBUSY, "Resource busy")

    with patch("board_aggregator.file_utils.os.replace", side_effect=always_busy), \
            patch("board_aggregator.file_utils.time.sleep"):
        with pytest.raises(OSError) as exc_info:
            write_csv(SAMPLE_JOBS, path)

    msg = str(exc_info.value)
    assert "locked" in msg.lower()
    assert "close the file" in msg.lower()
    assert "EBUSY" not in msg  # raw errno not leaked to the user
