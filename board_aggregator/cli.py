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

    from board_aggregator.scrapers import SCRAPER_REGISTRY

    if list_scrapers:
        click.echo("Available scrapers:")
        for name in sorted(SCRAPER_REGISTRY.keys()):
            click.echo(f"  - {name}")
        return

    queries = list(query) if query else DEFAULT_QUERIES
    scraper_filter = list(scraper) if scraper else None

    click.echo(f"Running {len(queries)} queries across {'all' if not scraper_filter else len(scraper_filter)} scrapers")
    click.echo(f"Output: {output_dir}")
    click.echo(f"Remote only: {remote_only}")
    click.echo(f"Hours old: {hours_old}")
    click.echo("---")

    jobs = run_all(
        queries=queries,
        output_dir=output_dir,
        is_remote=remote_only,
        scrapers=scraper_filter,
        portals_path=portals,
        hours_old=hours_old,
    )

    click.echo(f"\nDone! {len(jobs)} unique postings written to {output_dir}/")


if __name__ == "__main__":
    main()
