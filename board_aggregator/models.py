from pydantic import BaseModel, field_validator


class JobPosting(BaseModel):
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

    @field_validator("title", "company", mode="before")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v

    @field_validator("is_remote", mode="before")
    @classmethod
    def _coerce_remote(cls, v) -> bool:
        if v is None:
            return True
        return bool(v)

    @property
    def dedup_key(self) -> tuple[str, str]:
        return (self.title.lower(), self.company.lower())
