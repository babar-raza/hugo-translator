"""Agent Metrics API payload model — exact 17 Google Sheet fields.

No extra keys may be posted. Evidence-only fields live in metrics_evidence.py.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator, model_validator

AGENT_NAME = "Hugo Translator"
AGENT_OWNER = "Babar Raza"

VALID_STATUSES = {"success", "partial_success", "failure"}


class AgentMetricsPayload(BaseModel):
    """Strict model matching the exact Google Sheet columns (17 fields)."""

    timestamp: str = Field(description="ISO 8601 with timezone")
    agent_name: str = Field(default=AGENT_NAME)
    agent_owner: str = Field(default=AGENT_OWNER)
    job_type: str = Field(description="Content Translation | TM Improvement | Test")
    run_id: str = Field(description="segment_run_id UUID string")
    status: str = Field(description="success | partial_success | failure")
    product: str = Field(description="Aspose.Words, Aspose.Total, etc.")
    platform: str = Field(description=".NET, Java, All, etc.")
    website: str = Field(description="Source domain (aspose.net, aspose.org, etc.)")
    website_section: str = Field(description="Docs, KB, Blog, etc.")
    item_name: str = Field(description="Human-readable: action + family + section + file count")
    items_discovered: int = Field(ge=0)
    items_failed: int = Field(ge=0)
    items_succeeded: int = Field(ge=0)
    run_duration_ms: int = Field(ge=0)
    token_usage: int = Field(ge=0)
    api_calls_count: int = Field(ge=0)

    @field_validator("agent_name")
    @classmethod
    def validate_agent_name(cls, v: str) -> str:
        if v != AGENT_NAME:
            raise ValueError(f"agent_name must be '{AGENT_NAME}', got '{v}'")
        return v

    @field_validator("agent_owner")
    @classmethod
    def validate_agent_owner(cls, v: str) -> str:
        if v != AGENT_OWNER:
            raise ValueError(f"agent_owner must be '{AGENT_OWNER}', got '{v}'")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"status must be one of {VALID_STATUSES}, got '{v}'")
        return v

    @field_validator("website")
    @classmethod
    def validate_website_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("website must not be empty")
        return v

    @field_validator("item_name")
    @classmethod
    def validate_item_name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("item_name must not be empty")
        return v

    @model_validator(mode="after")
    def validate_item_counts(self) -> AgentMetricsPayload:
        if self.items_succeeded + self.items_failed > self.items_discovered:
            raise ValueError(
                f"items_succeeded ({self.items_succeeded}) + items_failed ({self.items_failed}) "
                f"> items_discovered ({self.items_discovered})"
            )
        return self

    @model_validator(mode="after")
    def validate_token_consistency(self) -> AgentMetricsPayload:
        if self.api_calls_count == 0 and self.token_usage != 0:
            raise ValueError("token_usage must be 0 when api_calls_count is 0")
        return self

    def to_post_dict(self) -> dict:
        """Return exactly 17 keys for posting. No extra keys."""
        return {
            "timestamp": self.timestamp,
            "agent_name": self.agent_name,
            "agent_owner": self.agent_owner,
            "job_type": self.job_type,
            "run_id": self.run_id,
            "status": self.status,
            "product": self.product,
            "platform": self.platform,
            "website": self.website,
            "website_section": self.website_section,
            "item_name": self.item_name,
            "items_discovered": self.items_discovered,
            "items_failed": self.items_failed,
            "items_succeeded": self.items_succeeded,
            "run_duration_ms": self.run_duration_ms,
            "token_usage": self.token_usage,
            "api_calls_count": self.api_calls_count,
        }


EXPECTED_POST_KEYS = {
    "timestamp",
    "agent_name",
    "agent_owner",
    "job_type",
    "run_id",
    "status",
    "product",
    "platform",
    "website",
    "website_section",
    "item_name",
    "items_discovered",
    "items_failed",
    "items_succeeded",
    "run_duration_ms",
    "token_usage",
    "api_calls_count",
}


def determine_status(items_succeeded: int, items_failed: int, items_discovered: int) -> str:
    """Determine status from item counts."""
    if items_discovered == 0:
        return "success"
    if items_failed == 0:
        return "success"
    if items_succeeded == 0:
        return "failure"
    return "partial_success"


def make_timestamp() -> str:
    """Generate ISO 8601 timestamp with UTC timezone."""
    return datetime.now(timezone.utc).isoformat()
