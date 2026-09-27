"""The shared, versioned contract for API, agents and saved runs."""
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        raise ValueError("时间必须包含时区，例如 2026-09-26T08:00:00Z")
    return value


class QuestionSpec(BaseModel):
    id: str = Field(default_factory=lambda: f"Q-{uuid4().hex[:8]}")
    question: str = Field(min_length=8, max_length=1000)
    as_of: datetime = Field(default_factory=utcnow)
    resolve_by: datetime | None = None
    outcomes: list[str] = Field(default_factory=lambda: ["是", "否"])
    resolution_rule: str = ""
    resolution_source: str | None = None
    mode: Literal["binary", "scenario"] = "binary"
    user_assumptions: list[str] = Field(default_factory=list)

    _aware_dates = field_validator("as_of", "resolve_by")(aware)

    @model_validator(mode="after")
    def check_resolution(self):
        if self.mode == "binary":
            if not self.resolve_by or not self.resolution_rule.strip():
                raise ValueError("二元预测需要截止时间和可核对的结算规则")
            if self.resolve_by <= self.as_of:
                raise ValueError("结算时间必须晚于信息截至时间")
            if len(self.outcomes) != 2 or len(set(self.outcomes)) != 2:
                raise ValueError("二元预测需要两个不同的结果选项")
        return self


class QuestionDraft(BaseModel):
    question: str = Field(min_length=8, max_length=1000)
    as_of: datetime = Field(default_factory=utcnow)
    resolve_by: datetime | None = None
    resolution_rule: str = ""
    resolution_source: str | None = None
    mode: Literal["binary", "scenario"] = "binary"
    user_assumptions: list[str] = Field(default_factory=list)

    _aware_dates = field_validator("as_of", "resolve_by")(aware)


class Evidence(BaseModel):
    id: str
    source_url: HttpUrl | None = None
    file_id: str | None = None
    title: str
    publisher: str | None = None
    published_at: datetime | None = None
    updated_at: datetime | None = None
    retrieved_at: datetime
    event_at: datetime | None = None
    excerpt: str = Field(min_length=1, max_length=12000)
    claim: str = ""
    snapshot_path: str | None = None
    content_hash: str
    source_type: Literal["primary", "secondary", "snippet_only", "imported", "exercise"]
    source_group: str
    date_status: Literal["verified", "unknown", "synthetic"] = "unknown"
    conflict_group: str | None = None

    _aware_dates = field_validator("published_at", "updated_at", "retrieved_at", "event_at")(aware)

    @model_validator(mode="after")
    def check_location(self):
        if not self.source_url and not self.file_id:
            raise ValueError("证据需要真实 URL 或文件 ID")
        return self


class ImportedEvidence(BaseModel):
    """Input shape; the server assigns IDs and content hashes."""
    id: str | None = None
    source_url: HttpUrl | None = None
    file_id: str | None = None
    title: str = Field(min_length=1)
    publisher: str | None = None
    published_at: datetime | None = None
    updated_at: datetime | None = None
    retrieved_at: datetime | None = None
    event_at: datetime | None = None
    excerpt: str = Field(min_length=1, max_length=12000)
    claim: str = ""
    snapshot_path: str | None = None
    source_type: Literal["imported", "exercise"] = "imported"
    source_group: str | None = None
    date_status: Literal["verified", "unknown", "synthetic"] = "unknown"

    _aware_dates = field_validator("published_at", "updated_at", "retrieved_at", "event_at")(aware)

    @model_validator(mode="after")
    def check_location(self):
        if not self.source_url and not self.file_id:
            raise ValueError("导入证据需要 source_url 或 file_id")
        return self


class QuestionAnalysis(BaseModel):
    normalized_question: str
    search_queries: list[str] = Field(min_length=1, max_length=3)
    caveats: list[str] = Field(default_factory=list)


class EvidenceAssessment(BaseModel):
    summary: str
    evidence_ids: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class Assumption(BaseModel):
    id: str
    created_by: Literal["user", "model"]
    parent_ids: list[str] = Field(default_factory=list)
    content: str
    rationale: str = ""


class ActorProfile(BaseModel):
    id: str
    name: str
    goal: str
    resources: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    visible_evidence_ids: list[str] = Field(default_factory=list)


class WorldState(BaseModel):
    state_version: int = 0
    summary: str
    variables: dict[str, str] = Field(default_factory=dict)
    relations: list[str] = Field(default_factory=list)
    actors: list[ActorProfile] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    simulation_branch_reason: str | None = None


class ActorAction(BaseModel):
    id: str
    created_by: str
    parent_ids: list[str] = Field(default_factory=list)
    actor_id: str
    round: int = Field(ge=1, le=2)
    parent_state: int
    action: str
    rationale_summary: str
    expected_impact: str
    evidence_ids: list[str] = Field(default_factory=list)
    assumption_ids: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    kind: Literal["simulation"] = "simulation"


class SimulationStep(BaseModel):
    id: str
    created_by: str = "environment"
    parent_ids: list[str] = Field(default_factory=list)
    round: int = Field(ge=1, le=2)
    parent_state: int
    next_state: int
    summary: str
    state_changes: dict[str, str] = Field(default_factory=dict)
    conflicts: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    assumption_ids: list[str] = Field(default_factory=list)
    kind: Literal["simulation"] = "simulation"


class ReviewIssue(BaseModel):
    severity: Literal["low", "medium", "high"]
    claim: str
    explanation: str
    affected_ids: list[str] = Field(default_factory=list)


class Review(BaseModel):
    status: Literal["passed", "qualified", "blocked"]
    probability_basis: Literal["full", "evidence_only", "none"] = "full"
    issues: list[ReviewIssue] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)


class EvidenceOnlyAudit(BaseModel):
    can_estimate: bool
    blocking_reasons: list[str] = Field(default_factory=list)


class Claim(BaseModel):
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    assumption_ids: list[str] = Field(default_factory=list)
    simulation_ids: list[str] = Field(default_factory=list)


class Forecast(BaseModel):
    status: Literal["completed", "insufficient_evidence", "scenario_only", "partial"]
    probability_basis: Literal["full", "evidence_only"] = "full"
    conclusion: str
    probabilities: dict[str, float] | None = None
    calibrated: Literal[False] = False
    supporting: list[Claim] = Field(default_factory=list)
    opposing: list[Claim] = Field(default_factory=list)
    key_assumptions: list[str] = Field(default_factory=list)
    scenarios: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    new_information: list[str] = Field(default_factory=list)


class EvidenceOnlyForecast(Forecast):
    """An approved evidence-only binary forecast cannot silently omit probability."""
    status: Literal["completed"] = "completed"
    probability_basis: Literal["evidence_only"] = "evidence_only"
    probabilities: dict[str, float]


class SettlementRequest(BaseModel):
    """A manually verified outcome, recorded only after the resolution deadline."""
    outcome: str = Field(min_length=1)
    source_url: HttpUrl
    source_title: str = Field(default="", max_length=300)
    observed_value: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=1000)


class Settlement(SettlementRequest):
    recorded_at: datetime = Field(default_factory=utcnow)
    forecast_probabilities: dict[str, float] | None = None
    brier_score: float | None = None

    _aware_recorded_at = field_validator("recorded_at")(aware)


class RunRequest(BaseModel):
    question: QuestionSpec
    evidence_mode: Literal["import", "online", "reuse", "demo"] = "import"
    evidence: list[ImportedEvidence] = Field(default_factory=list)
    parent_run_id: str | None = None


class RunRecord(BaseModel):
    run_id: str
    question_version: int = 1
    parent_run_id: str | None = None
    question: QuestionSpec
    evidence_mode: str
    demo: bool = False
    status: Literal["queued", "running", "completed", "insufficient_evidence", "scenario_only", "partial", "failed", "interrupted"] = "queued"
    stage: str = "queued"
    failed_stage: str | None = None
    stage_durations: dict[str, float] = Field(default_factory=dict)
    stage_outputs: dict[str, object] = Field(default_factory=dict)
    question_analysis: QuestionAnalysis | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    evidence_assessment: EvidenceAssessment | None = None
    world: WorldState | None = None
    actions: list[ActorAction] = Field(default_factory=list)
    simulation: list[SimulationStep] = Field(default_factory=list)
    review: Review | None = None
    forecast: Forecast | None = None
    settlement: Settlement | None = None
    model: str
    prompt_version: str = "v2"
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    usage: dict[str, int] = Field(default_factory=lambda: {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
    errors: list[str] = Field(default_factory=list)
    retry_history: list[str] = Field(default_factory=list)
    resume_count: int = 0
