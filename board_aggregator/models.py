from __future__ import annotations

import re
from datetime import date

from pydantic import AnyUrl, BaseModel, ConfigDict, TypeAdapter, ValidationError, field_validator

_url_adapter = TypeAdapter(AnyUrl)
_URL_SCHEMES = {"http", "https"}

# A verified application deadline is a real ISO calendar date written in the
# canonical YYYY-MM-DD form. The regex pins the shape (rejecting fromisoformat's
# looser accepted spellings like "20260619" or the ISO week form "2026-W25-4"),
# and date.fromisoformat then proves the date is real (rejecting "2026-13-99").
# Anything else (e.g. "TOMORROW", "closes soon", "ASAP") is a fabrication risk
# and is rejected at the model layer so no agent can smuggle urgency framing
# through a free-text deadline string. See CLAUDE.md forbidden patterns (never
# fabricate a deadline).
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class JobPosting(BaseModel):
    # validate_assignment closes the post-creation mutation bypass: reassigning
    # job_url / application_deadline after construction re-runs the validators
    # below, so a validated field can never be overwritten with an invalid value.
    model_config = ConfigDict(validate_assignment=True)

    title: str
    company: str
    source: str
    job_url: str
    location: str | None = None
    is_remote: bool = True
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str = "USD"
    salary_interval: str = "yearly"
    date_posted: str | None = None
    job_type: str | None = None
    description: str | None = None
    application_deadline: str | None = None

    @field_validator("title", "company", mode="before")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v

    @field_validator("job_url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        # Reject empty/non-URL strings (a fabricated link risk) and require an
        # http(s) scheme so non-web URLs (javascript:/data:/mailto:/tel:/ftp:/
        # about:, or a Windows path like C:\... which parses as scheme "c") can
        # never reach a job_url. Return the original string unchanged so a valid
        # URL is preserved byte-for-byte (AnyUrl normalizes, e.g. appending a
        # trailing slash).
        parsed = _url_adapter.validate_python(v)
        if parsed.scheme not in _URL_SCHEMES:
            raise ValueError(
                f"job_url must be an http(s) URL; got scheme {parsed.scheme!r} in {v!r}"
            )
        return v

    @field_validator("application_deadline")
    @classmethod
    def _validate_deadline(cls, v: str | None) -> str | None:
        # Only an unverified deadline (None) or a real ISO date is allowed. A
        # free-text string ("TOMORROW", "ASAP", "") is a fabricated-deadline risk
        # and must never reach the model — urgency framing is gated on this field.
        if v is None:
            return None
        stripped = v.strip() if isinstance(v, str) else v
        # Shape gate (YYYY-MM-DD) then a real-calendar-date check: the regex
        # rules out wrong shapes ("2026/06/19", "June 19") and fromisoformat
        # rules out impossible dates ("2026-13-99", "2026-02-30") that a shape
        # check alone would let through.
        if not isinstance(stripped, str) or not _ISO_DATE.match(stripped):
            raise ValueError(
                "application_deadline must be an ISO date (YYYY-MM-DD) or None; "
                f"got {v!r} (free-text deadlines are a fabrication risk)"
            )
        try:
            date.fromisoformat(stripped)
        except ValueError:
            raise ValueError(
                "application_deadline must be a real calendar date "
                f"(YYYY-MM-DD) or None; got {v!r} (invalid dates are a "
                "fabrication risk)"
            ) from None
        return stripped

    @field_validator("is_remote", mode="before")
    @classmethod
    def _coerce_remote(cls, v) -> bool:
        if v is None:
            return True
        return bool(v)

    @property
    def dedup_key(self) -> tuple[str, str]:
        return (self.title.lower(), self.company.lower())

    @property
    def has_verified_deadline(self) -> bool:
        # Model-layer gate for urgency framing: only True when a real deadline was
        # retrieved from a source. Callers (agents/CLI) MUST check this before
        # emitting deadline/urgency language ("closes TOMORROW"); when False the
        # deadline is unverified and urgency framing is forbidden.
        return self.application_deadline is not None

    @classmethod
    def try_create(cls, **fields) -> JobPosting | None:
        """Construct a JobPosting, or return None if the input is invalid.

        Scrapers with empty-URL fallback paths (job_url="" when a slug/permalink
        is missing) MUST use this instead of the raw constructor so an unverified
        posting is skipped gracefully rather than crashing the whole scrape:

            job = JobPosting.try_create(...)
            if job is None:
                continue

        The direct constructor still raises ValidationError on invalid input so
        the fabrication guard stays loud for callers that expect valid data.
        """
        try:
            return cls(**fields)
        except ValidationError:
            return None
