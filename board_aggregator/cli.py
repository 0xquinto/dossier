from pathlib import Path

import click

from board_aggregator.runner import run_all

DEFAULT_QUERIES = [
    "Operations Manager AI",
    "AI Operations Lead",
    "Business Operations AI Integration",
    "AI Process Automation Manager",
    "Technical Operations Manager",
    "AI Agent Developer",
    "Developer Relations",
]

DEFAULT_OUTPUT = Path("research/phase-1-scrape")


def load_board_filter(portals_path):
    """Read the optional per-user board allow/deny filter from portals.yml.

    Returns (allowlist, denylist), each a list or None. Default (no portals
    file, or no `boards:` section) is (None, None) = every board enabled, so
    existing CLI usage is unaffected.
    """
    if not portals_path:
        return None, None

    import yaml

    try:
        data = yaml.safe_load(Path(portals_path).read_text()) or {}
    except yaml.YAMLError as exc:
        raise click.ClickException(f"Could not parse {portals_path}: {exc}")
    if not isinstance(data, dict):
        raise click.ClickException(
            f"{portals_path} is not a valid portals file (expected a YAML mapping)"
        )
    boards = data.get("boards", {}) or {}
    allowlist = boards.get("allow")
    denylist = boards.get("deny")
    return allowlist, denylist


@click.command()
@click.option(
    "-q", "--query",
    multiple=True,
    help="Search query (can specify multiple). Defaults to 7 built-in queries.",
)
@click.option(
    "-o", "--output-dir",
    type=click.Path(path_type=Path),
    default=DEFAULT_OUTPUT,
    help=f"Output directory. Default: {DEFAULT_OUTPUT}",
)
@click.option(
    "-s", "--scraper",
    multiple=True,
    help="Run only specific scrapers (e.g., -s himalayas -s hn_hiring). Default: all.",
)
@click.option(
    "--remote-only/--include-onsite",
    default=True,
    help="Only include remote jobs. Default: remote-only.",
)
@click.option(
    "--hours-old",
    type=int,
    default=168,
    help="Drop postings older than N hours (24 = posted today, 168 = last 7 days). Default: 168.",
)
@click.option(
    "-p", "--portals",
    type=click.Path(exists=True),
    default=None,
    help="Path to portals.yml for targeted company scanning.",
)
@click.option(
    "--list-scrapers",
    is_flag=True,
    help="List all available scrapers and exit.",
)
def main(query, output_dir, scraper, remote_only, hours_old, portals, list_scrapers):
    """dossier Scraper -- Multi-board job scraper for the dossier pipeline."""
    # Import here to trigger registration via module imports
    import board_aggregator.scrapers.jobspy_boards  # noqa: F401
    import board_aggregator.scrapers.himalayas  # noqa: F401
    import board_aggregator.scrapers.weworkremotely  # noqa: F401
    import board_aggregator.scrapers.hn_hiring  # noqa: F401
    import board_aggregator.scrapers.hn_freelancer  # noqa: F401
    import board_aggregator.scrapers.cryptojobslist  # noqa: F401
    import board_aggregator.scrapers.crypto_jobs  # noqa: F401
    import board_aggregator.scrapers.web3career  # noqa: F401
    import board_aggregator.scrapers.cryptocurrencyjobs  # noqa: F401
    import board_aggregator.scrapers.remoteok  # noqa: F401
    import board_aggregator.scrapers.reddit_jobs  # noqa: F401
    import board_aggregator.scrapers.indiehackers  # noqa: F401
    import board_aggregator.scrapers.nocodejobs  # noqa: F401
    import board_aggregator.scrapers.eighty_thousand_hours  # noqa: F401

    from board_aggregator.scrapers import SCRAPER_REGISTRY, filter_scrapers

    # Per-user board allow/deny filter from portals.yml (default: all enabled).
    allowlist, denylist = load_board_filter(portals)
    try:
        enabled = filter_scrapers(sorted(SCRAPER_REGISTRY.keys()), allowlist, denylist)
    except ValueError as exc:
        raise click.ClickException(f"Invalid board filter in {portals}: {exc}")

    if list_scrapers:
        click.echo("Available scrapers:")
        for name in enabled:
            click.echo(f"  - {name}")
        return

    queries = list(query) if query else DEFAULT_QUERIES
    # Explicit -s narrows the run; otherwise honor the portals.yml board filter.
    if scraper:
        scraper_filter = [n for n in scraper if n in enabled]
        if not scraper_filter:
            # Every requested scraper is denied/disabled by the portals filter.
            # An empty list now means "run zero boards" (C2), so refuse rather
            # than silently scrape nothing.
            raise click.ClickException(
                f"No requested scrapers remain after the board filter: "
                f"-s {' '.join(scraper)} intersects the enabled set to empty. "
                f"Enabled: {', '.join(enabled) or '(none)'}."
            )
    elif allowlist or denylist:
        scraper_filter = enabled
        if not scraper_filter:
            # The portals.yml board filter denied/excluded every available
            # board. An empty list now means "run zero boards" (C2), so refuse
            # rather than silently scrape nothing with no -s given.
            raise click.ClickException(
                f"No boards remain after the portals.yml board filter in {portals}: "
                f"the allow/deny rules exclude every available scraper."
            )
    else:
        scraper_filter = None

    click.echo(f"Running {len(queries)} queries across {'all' if not scraper_filter else len(scraper_filter)} scrapers")
    click.echo(f"Output: {output_dir}")
    click.echo(f"Remote only: {remote_only}")
    click.echo(f"Hours old: {hours_old}")
    click.echo("---")

    try:
        jobs = run_all(
            queries=queries,
            output_dir=output_dir,
            is_remote=remote_only,
            scrapers=scraper_filter,
            portals_path=portals,
            hours_old=hours_old,
        )
    except FileExistsError as exc:
        # Write-once guard tripped (a second run into the same dir). Surface the
        # guidance as a clean CLI error, not a traceback.
        raise click.ClickException(str(exc))
    except OSError as exc:
        # A locked/unwritable output file (e.g. all-postings.csv open in Excel on
        # Windows) exhausts atomic_write_text's retries and raises a bare OSError
        # whose message is already user-ready. Surface it cleanly, not as a
        # traceback. (FileExistsError is an OSError subclass, so it is caught
        # above first.)
        raise click.ClickException(str(exc))

    click.echo(f"\nDone! {len(jobs)} unique postings written to {output_dir}/")


if __name__ == "__main__":
    main()
