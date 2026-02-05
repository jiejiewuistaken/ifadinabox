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
    output_type: Literal["cosop", "pcn", "pdr"] = "cosop"
    num_simulations: int = 1
    max_rounds: int = 3
    top_candidates: int = 5


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


class ReviewMetric(BaseModel):
    id: Literal[
        "strategic_consistency",
        "country_priority_match",
        "technical_feasibility",
        "compliance_risk",
        "innovation",
    ]
    label: str
    score: float
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
    metrics: list[ReviewMetric] = Field(default_factory=list)


class ForecastResult(BaseModel):
    phase: Literal["on_track", "watchlist", "at_risk"]
    confidence: float
    rationale: str


class CandidateResult(BaseModel):
    candidate_id: str
    score: float
    passed: bool
    round: int
    draft_path: str
    pdf_path: str | None = None
    review: ReviewResult
    ren_review: ReviewResult | None = None
    ode_review: ReviewResult | None = None
    osc_review: ReviewResult | None = None
    qag_review: ReviewResult | None = None
    stage_gates: dict[str, bool] = Field(default_factory=dict)
    stage_notes: dict[str, str] = Field(default_factory=dict)
    forecast: ForecastResult | None = None
    created_at: str = Field(default_factory=utcnow_iso)


class RunStatus(BaseModel):
    run_id: str
    project_id: str
    status: Literal["queued", "ingesting", "writing", "reviewing", "rendering", "completed", "failed"]
    round: int = 0
    max_rounds: int = 2
    error: str | None = None
    artifacts: dict[str, Any] = Field(default_factory=dict)
    review: ReviewResult | None = None
    candidates: list[CandidateResult] = Field(default_factory=list)
    selected_candidates: list[str] = Field(default_factory=list)
    forecast: ForecastResult | None = None

