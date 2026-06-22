"""Pydantic output schemas for the Exa Agent `outputSchema`.

These models describe the *answer* an Exa Agent run returns for the two
research jobs the shared core exposes (spec §2):

- ``ReconResult`` — `recon-3`'s contact + company-context job.
- ``DiscoverResult`` — `discoverer-6`'s ICP company list-build job.

Design constraint (spec §3, "own-fetch verifies, grounding leads"): grounding
is a SEPARATE ``output.grounding`` field on the Exa run, surfaced as an audit
trace — it is NOT embedded in these answer schemas. So there is deliberately no
``confidence``/``verified`` field here: verification is earned later by the
agent's own full-page fetch + verbatim match, never by Exa marking its own
homework. Letting the answer schema carry a confidence flag would invite
exactly that anti-pattern, so the field is omitted by design.

``json_schema(model)`` exports a model as a plain JSON-Schema dict suitable for
passing as Exa's ``outputSchema``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Supported ATS portals (discoverer-6 stores the matching slug/careers_url).
# Mirrors the ats set in the discoverer-6 prompt: greenhouse/ashby/lever/workday
# (+ null). Constraining it here also tightens the exported Exa ``outputSchema``.
Ats = Literal["greenhouse", "ashby", "lever", "workday"]


class Contact(BaseModel):
    """A candidate hiring-side contact returned by an Exa Agent run.

    A returned value is a *candidate*, not a verified fact: the agent must
    fetch the page itself and match the value verbatim before any field may be
    treated as verified (spec §3). No confidence field lives here — that label
    is derived downstream from the agent's own fetch.
    """

    name: str
    title: str | None = None
    linkedin: str | None = None
    email: str | None = None
    x: str | None = None
    recent_activity: str | None = None


class ReconResult(BaseModel):
    """`recon-3` answer schema: the primary contact, alternatives, and context."""

    primary_contact: Contact
    alternative_contacts: list[Contact] = Field(default_factory=list)
    company_context: str | None = None


class Company(BaseModel):
    """A candidate ICP-fit company returned by a `discoverer-6` Exa Agent run."""

    name: str
    domain: str | None = None
    ats: Ats | None = None
    slug: str | None = None
    careers_url: str | None = None
    icp_fit_score: float | None = Field(
        default=None,
        ge=0,
        le=10,
        description="ICP-fit score on the canonical 1-10 scale (discoverer-6's "
        "icp_min_score gate assumes 1-10).",
    )
    icp_fit_reasoning: str | None = None


class DiscoverResult(BaseModel):
    """`discoverer-6` answer schema: the discovered ICP-fit company list."""

    companies: list[Company] = Field(default_factory=list)


def json_schema(model: type[BaseModel]) -> dict:
    """Export a Pydantic model as a JSON-Schema dict for Exa's ``outputSchema``.

    Exa's Agent API takes a plain JSON Schema; Pydantic's ``model_json_schema``
    produces exactly that, so this is a thin, named seam the client can call.
    """
    return model.model_json_schema()
