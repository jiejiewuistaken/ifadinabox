from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utcnow_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


class ProjectCreateResponse(BaseModel):
    project_id: str


class ProjectInputs(BaseModel):
    country: str | None = None
    title: str | None = None
    user_notes: str = ""


class RunCreateResponse(BaseModel):
    run_id: str


EventType = Literal[
    "log",
    "graph_update",
    "round_update",
    "draft_created",
    "review_result",
    "run_status",
]


class RunEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    ts: str = Field(default_factory=utcnow_iso)
    type: EventType
    payload: dict[str, Any]


class CheckboxStatus(BaseModel):
    id: str
    label: str
    status: Literal["true", "false", "partial"]
    rationale: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class ReviewComment(BaseModel):
    severity: Literal["blocker", "major", "minor"]
    section: str
    comment: str
    suggestion: str | None = None


class ReviewResult(BaseModel):
    passed: bool
    comments: list[ReviewComment]
    checkboxes: list[CheckboxStatus]


class RunStatus(BaseModel):
    run_id: str
    project_id: str
    status: Literal["queued", "ingesting", "writing", "reviewing", "rendering", "completed", "failed"]
    round: int = 0
    max_rounds: int = 2
    error: str | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)
    review: ReviewResult | None = None

