import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from board_aggregator.exa_schemas import (
    Company,
    Contact,
    DiscoverResult,
    ReconResult,
    json_schema,
)

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_recon_result_validates_sample():
    result = ReconResult.model_validate(
        {
            "primary_contact": {
                "name": "Jane Doe",
                "title": "Head of Engineering",
                "linkedin": "https://linkedin.com/in/janedoe",
                "email": "jane@acme.com",
                "x": "https://x.com/janedoe",
                "recent_activity": "Posted about hiring AI engineers.",
            },
            "alternative_contacts": [{"name": "John Roe", "title": "Recruiter"}],
            "company_context": "Series B, 80 people, AI infra.",
        }
    )
    assert result.primary_contact.name == "Jane Doe"
    assert result.primary_contact.email == "jane@acme.com"
    assert len(result.alternative_contacts) == 1
    assert result.alternative_contacts[0].name == "John Roe"
    assert result.company_context.startswith("Series B")


def test_recon_result_minimal_contact():
    # Only name is required on a contact; everything else is an optional
    # candidate field (the agent fills what the source supports).
    result = ReconResult.model_validate({"primary_contact": {"name": "Jane Doe"}})
    assert result.primary_contact.title is None
    assert result.alternative_contacts == []
    assert result.company_context is None


def test_recon_result_requires_primary_contact():
    with pytest.raises(ValidationError):
        ReconResult.model_validate({"company_context": "no contact here"})


def test_discover_result_validates_sample():
    result = DiscoverResult.model_validate(
        {
            "companies": [
                {
                    "name": "Acme",
                    "domain": "acme.com",
                    "ats": "greenhouse",
                    "slug": "acme",
                    "careers_url": "https://boards.greenhouse.io/acme",
                    "icp_fit_score": 0.92,
                    "icp_fit_reasoning": "AI infra, hiring ops roles.",
                },
                {"name": "Beta Co"},
            ]
        }
    )
    assert len(result.companies) == 2
    assert result.companies[0].ats == "greenhouse"
    assert result.companies[0].icp_fit_score == 0.92
    assert result.companies[1].domain is None


def test_discover_result_defaults_empty():
    result = DiscoverResult.model_validate({})
    assert result.companies == []


def test_no_confidence_field_in_answer_schema():
    # Spec §3: grounding/verification is a SEPARATE output.grounding field and is
    # earned by the agent's own fetch — it must NOT be embedded in the answer
    # schema. Guard that no confidence/verified flag leaks into these models.
    forbidden = {"confidence", "verified", "grounding"}
    for model in (Contact, Company, ReconResult, DiscoverResult):
        assert forbidden.isdisjoint(model.model_fields), (
            f"{model.__name__} must not carry a verification field in the answer schema"
        )


def test_json_schema_export_recon():
    schema = json_schema(ReconResult)
    assert isinstance(schema, dict)
    assert schema["type"] == "object"
    assert "primary_contact" in schema["properties"]
    assert "primary_contact" in schema["required"]


def test_json_schema_export_discover():
    schema = json_schema(DiscoverResult)
    assert isinstance(schema, dict)
    assert schema["type"] == "object"
    assert "companies" in schema["properties"]


def test_dossier_research_entry_point_registered():
    data = tomllib.loads(PYPROJECT.read_text())
    scripts = data["project"]["scripts"]
    assert scripts["dossier-research"] == "board_aggregator.exa_cli:main"
    # board-aggregator stays untouched (non-breaking).
    assert scripts["board-aggregator"] == "board_aggregator.cli:main"


def test_exa_py_declared_dependency():
    data = tomllib.loads(PYPROJECT.read_text())
    deps = data["project"]["dependencies"]
    assert any(d.startswith("exa-py") for d in deps)
