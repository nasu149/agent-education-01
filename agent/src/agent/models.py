"""Pydantic models used at Agent boundaries."""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class Diagnosis(BaseModel):
    """Structured judgment produced after the free-form investigation loop."""

    root_cause: str = Field(description="Most likely root cause, stated concretely.")
    evidence: list[str] = Field(
        min_length=1,
        description="Observed facts that support the root-cause judgment.",
    )
    recommended_action: Literal[
        "start_container",
        "restart_container",
        "terminate_postgres_connections",
        "manual",
        "none",
    ] = Field(description="Smallest safe remediation available to this Agent.")
    target_service: Literal["httpd", "tomcat", "postgres", "none"]
    target_application: str = Field(
        default="none",
        description=(
            "PostgreSQL application_name to terminate when recommended_action is "
            "terminate_postgres_connections; otherwise use 'none'."
        ),
    )
    action_reason: str = Field(description="Why this action is appropriate and safe enough to propose.")
    confidence: Literal["low", "medium", "high"]


class ApprovalRequest(BaseModel):
    """JSON-serializable payload shown to a human at the HITL boundary."""

    action: str
    target_service: str
    target_application: str = "none"
    root_cause: str
    evidence: list[str]
    reason: str


class ApprovalBody(BaseModel):
    """HTTP request body used by the training UI to resume an interrupted graph."""

    approved: bool
