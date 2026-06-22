"""``dossier-research`` CLI — the Bash-reachable face over the Exa Agent client.

This is the thin command surface `recon-3` / `discoverer-6` reach via scoped
Bash (spec §1, §2). It does the minimum a CLI should and nothing the agent owns:

- **Results are prompts** — it emits a single *structured JSON* document
  (result + grounding trace + cost), size-capped. The AGENT renders the
  markdown and does the §3 own-fetch verification; the CLI never stamps a
  field ``verified`` and never renders prose.
- **Descriptions are prompts** — ``--help`` states *when* to reach for
  ``recon`` vs ``discover``.
- **Errors are prompts** — the client's typed exceptions (missing key,
  rate-limit / 2-concurrent cap, cost-cap, no-progress, breaker-open) render
  as friendly, actionable messages, never a traceback.

What the CLI deliberately does NOT do: it does not write ``portals.yml`` and
does not validate / probe careers URLs — the agent runs ``probe-portal``
(spec §1, §2). ``discover`` only returns candidate companies as JSON.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NoReturn

import click

from board_aggregator.exa_agent import ExaAgentClient, ExaAgentError

# §2 results-are-prompts: the structured return is size-capped so a stray giant
# field can't blow up the agent's context. Long free-text fields are truncated.
_MAX_TEXT_CHARS = 4000


def _build_client(**kwargs) -> ExaAgentClient:
    """Construct the shared client (default factory reads EXA_API_KEY).

    Pulled out as a seam so tests patch it with a fake instead of touching
    ``exa-py`` or the network.
    """
    return ExaAgentClient(**kwargs)


def _cap_text(value):
    """Truncate an over-long free-text field (§2 size-capped)."""
    if isinstance(value, str) and len(value) > _MAX_TEXT_CHARS:
        return value[:_MAX_TEXT_CHARS] + "…[truncated]"
    return value


def _capped_result(result) -> dict:
    """Dump a Pydantic result to a dict, truncating long free-text fields."""
    data = result.model_dump()
    if isinstance(data.get("company_context"), str):
        data["company_context"] = _cap_text(data["company_context"])
    for company in data.get("companies", []) or []:
        if isinstance(company.get("icp_fit_reasoning"), str):
            company["icp_fit_reasoning"] = _cap_text(company["icp_fit_reasoning"])
    return data


def _emit(result, grounding, cost, run_dir) -> None:
    """Write the cost trace into run_dir (if given) and emit the JSON payload.

    ``grounding`` is surfaced as a SEPARATE audit trace (§3), never folded into
    the answer. The whole payload is structured JSON — the agent renders it.
    """
    if run_dir:
        run_path = Path(run_dir)
        run_path.mkdir(parents=True, exist_ok=True)
        (run_path / "exa-cost.json").write_text(
            json.dumps(cost, ensure_ascii=False, indent=2)
        )

    payload = {
        "result": _capped_result(result),
        "grounding": grounding,
        "cost": cost,
    }
    click.echo(json.dumps(payload, ensure_ascii=False))


@click.group()
def main() -> None:
    """dossier-research -- Exa Agent web research for the dossier pipeline.

    Two jobs, both emitting structured JSON (the agent renders the markdown
    and does its own-fetch verification):

    \b
      recon     Find the hiring manager + company context for ONE role.
      discover  Build an ICP-fit company list to seed portals.yml.
    """


@main.command()
@click.option("--company", required=True, help="Company name for the role.")
@click.option("--role", required=True, help="Role title being researched.")
@click.option("--url", required=True, help="Job posting URL.")
@click.option(
    "--run-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Run directory; the cost trace is logged here (meta material).",
)
@click.option(
    "--effort",
    type=click.Choice(["low", "medium", "high", "auto"]),
    default="medium",
    show_default=True,
    help="Exa Agent effort tier. recon defaults to medium (flat, predictable).",
)
@click.option(
    "--enrich/--no-enrich",
    "enrich",
    default=False,
    help="Enrich contacts with email/LinkedIn (adds per-contact cost).",
)
def recon(company, role, url, run_dir, effort, enrich) -> None:
    """Research ONE role: the hiring manager / decision maker + company context.

    Emits structured JSON (result + grounding trace + cost). Returned contacts
    are CANDIDATES, not verified facts — the agent must fetch the page itself
    and match verbatim before treating any field as verified (§3).
    """
    client = _build_or_exit()
    try:
        result, grounding, cost = client.run_recon(
            company=company,
            role=role,
            url=url,
            effort=effort,
            enrich_contacts=enrich,
        )
    except ExaAgentError as exc:
        _fail(exc)
    _emit(result, grounding, cost, run_dir)


@main.command()
@click.option("--icp", default=None, help="Ideal-customer-profile description.")
@click.option(
    "--skills-inventory",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to skills-inventory.md; its content folds into the ICP.",
)
@click.option(
    "--max-items",
    type=int,
    default=20,
    show_default=True,
    help="Upper bound on companies returned (caps cost; §5).",
)
@click.option(
    "--effort",
    type=click.Choice(["low", "medium", "high", "auto"]),
    default="auto",
    show_default=True,
    help="Exa Agent effort tier. discover defaults to auto.",
)
@click.option(
    "--run-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Run directory; the cost trace is logged here (meta material).",
)
def discover(icp, skills_inventory, max_items, effort, run_dir) -> None:
    """Build an ICP-fit company list (candidates only).

    Emits the candidate companies as JSON. It does NOT write portals.yml and
    does NOT validate / probe careers URLs — the agent runs probe-portal on the
    candidates before anything is persisted (§1, §2).
    """
    icp_text = _resolve_icp(icp, skills_inventory)
    client = _build_or_exit()
    try:
        result, grounding, cost = client.run_discover(
            icp=icp_text,
            max_items=max_items,
            effort=effort,
        )
    except ExaAgentError as exc:
        _fail(exc)
    _emit(result, grounding, cost, run_dir)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _resolve_icp(icp, skills_inventory) -> str:
    """Fold --skills-inventory file content into the ICP input.

    At least one of --icp / --skills-inventory is required.
    """
    parts = []
    if icp:
        parts.append(icp)
    if skills_inventory:
        parts.append(Path(skills_inventory).read_text().strip())
    if not parts:
        raise click.UsageError(
            "Provide --icp and/or --skills-inventory: discover needs an ICP to "
            "search against."
        )
    return "\n\n".join(p for p in parts if p)


def _build_or_exit() -> ExaAgentClient:
    """Build the client, rendering a credential/build error as a prompt."""
    try:
        return _build_client()
    except ExaAgentError as exc:
        _fail(exc)


def _fail(exc: ExaAgentError) -> NoReturn:
    """Render a typed client exception as a friendly, actionable CLI error.

    The exception messages are already prompt-shaped (errors-are-prompts, §2);
    surfacing them via ClickException gives a clean non-zero exit with no
    traceback.
    """
    raise click.ClickException(str(exc))


if __name__ == "__main__":
    main()
