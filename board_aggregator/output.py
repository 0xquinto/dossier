import csv
import io
import json
from collections import Counter
from datetime import date
from pathlib import Path

from board_aggregator.file_utils import atomic_write_text
from board_aggregator.models import JobPosting

CSV_FIELDS = [
    "title", "company", "source", "job_url", "location", "is_remote",
    "salary_min", "salary_max", "salary_currency", "salary_interval",
    "date_posted", "job_type", "description", "hww_listed", "hww_process",
]

# Compact machine-readable index fields (T2-7): the minimal subset agents
# need to score postings without reading the full human-facing markdown.
# Includes location + application_deadline because ranker-7 reads this index
# exclusively yet scores location-fit and deadline-urgency (I3).
# hww_listed/hww_process are added per-record only on matched postings (the
# small minority), so the unmatched majority doesn't pay ~40 bytes/record
# against the index size budget (see board_aggregator.hww).
INDEX_FIELDS = [
    "title", "company", "salary_min", "salary_max",
    "source", "job_url", "is_remote", "location", "application_deadline",
]


def _csv_value(val):
    """Convert value for CSV: None -> '', float whole numbers -> int string."""
    if val is None:
        return ""
    if isinstance(val, float) and val == int(val):
        return str(int(val))
    return val


def write_csv(jobs: list[JobPosting], path: Path, *, overwrite: bool = False) -> None:
    if not overwrite and path.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing file: {path}. "
            "Use a fresh run directory or pass overwrite=True."
        )

    # Serialize to a string buffer, then route through the lock-aware atomic
    # writer (T3-2): a raw open() would crash with an unhandled OSError(EBUSY)
    # when all-postings.csv is open in an editor, unlike the markdown/index
    # paths. ``newline=""`` keeps csv's own line terminators intact.
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for job in jobs:
        row = job.model_dump()
        writer.writerow({k: _csv_value(row.get(k)) for k in CSV_FIELDS})

    # overwrite=True here: the write-once guard already ran above, and the
    # atomic temp+rename must be free to replace its own .tmp scratch file.
    atomic_write_text(path, buf.getvalue(), overwrite=True)


def write_markdown(jobs: list[JobPosting], path: Path, *, overwrite: bool = False) -> None:
    if not overwrite and path.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing file: {path}. "
            "Use a fresh run directory or pass overwrite=True."
        )

    source_counts = Counter(j.source for j in jobs)
    source_summary = ", ".join(f"{src}: {cnt}" for src, cnt in source_counts.most_common())

    lines: list[str] = []
    lines.append("# Phase 1: Job Board Scrape Results")
    lines.append(f"**Date:** {date.today().isoformat()}")
    lines.append(f"**Total Postings (unique after dedup):** {len(jobs)}")
    lines.append(f"**By Board:** {source_summary}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for job in jobs:
        lines.append(f"## {job.title} -- {job.company}")
        lines.append(f"- **Source:** {job.source}")
        lines.append(f"- **Location:** {job.location or 'Remote'}")
        lines.append(f"- **Is Remote:** {job.is_remote}")

        if job.salary_min and job.salary_max:
            lines.append(
                f"- **Salary:** ${job.salary_min:,.0f} - ${job.salary_max:,.0f} {job.salary_currency} ({job.salary_interval})"
            )
        elif job.salary_min:
            lines.append(f"- **Salary:** ${job.salary_min:,.0f}+ {job.salary_currency}")
        else:
            lines.append("- **Salary:** Not listed")

        lines.append(f"- **URL:** {job.job_url}")
        if job.date_posted:
            lines.append(f"- **Date Posted:** {job.date_posted}")
        if job.job_type:
            lines.append(f"- **Job Type:** {job.job_type}")
        if job.description:
            lines.append(f"- **Description:** {job.description[:300]}")
        if job.hww_listed:
            lines.append("- **Hiring Without Whiteboards:** Listed (community-sourced, unverified)")
            if job.hww_process:
                lines.append(f"- **HWW Process Note:** {job.hww_process}")
        lines.append("---")
        lines.append("")

    # UTF-8 + lock-aware atomic write (T2-1/T3-3 encoding, T3-2 file locks).
    # overwrite=True here: the write-once guard already ran above, and the
    # atomic temp+rename must be free to replace its own .tmp scratch file.
    atomic_write_text(path, "\n".join(lines), overwrite=True)


def write_compact_index(jobs: list[JobPosting], path: Path, *, overwrite: bool = False) -> None:
    """Write a compact JSON index of postings for agents to read via code.

    The full markdown blows past the agent read cap (T2-7); this minimal
    JSON keeps the machine-readable view small enough to load in one call.
    """
    if not overwrite and path.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing file: {path}. "
            "Use a fresh run directory or pass overwrite=True."
        )
    records = []
    for job in jobs:
        record = {k: getattr(job, k) for k in INDEX_FIELDS}
        if job.hww_listed:
            record["hww_listed"] = True
            record["hww_process"] = job.hww_process
        records.append(record)
    atomic_write_text(
        path,
        json.dumps(records, ensure_ascii=False, separators=(",", ":")),
        overwrite=True,
    )
