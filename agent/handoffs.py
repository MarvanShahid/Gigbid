"""Structured hand-offs between agents (C3). Anything a later step decides on is one of these."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Requirement(BaseModel):
    text: str
    skills: list[str] = Field(default_factory=list, description="canonical skill ids named or implied")
    must_have: bool = True


class JobSpec(BaseModel):
    job_id: str
    title: str
    category: str
    summary: str = Field(description="one sentence, in our words, of what the client wants")
    deliverables: list[str] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    budget_amount: float = 0
    budget_type: Literal["fixed", "hourly"] = "fixed"
    timeline_weeks: float | None = None
    screening_questions: list[str] = Field(default_factory=list)
    hidden_needs: list[str] = Field(default_factory=list, description="needs the client implies but does not state")
    source: Literal["llm", "rules"] = "rules"


RiskKind = Literal["scam", "free_work", "off_platform", "injection", "unverified_payment", "no_hires", "lowball",
                   "poor_reviews", "vague"]


class RiskFlag(BaseModel):
    kind: RiskKind
    evidence: str = Field(description="the text or fact that triggered the flag")
    weight: float = Field(ge=0, le=1)


class RiskReport(BaseModel):
    score: float = Field(ge=0, le=1, description="0 safe .. 1 certain scam")
    level: Literal["low", "medium", "high"]
    is_scam: bool
    injection_detected: bool = False
    client_quality: float = Field(ge=0, le=1)
    flags: list[RiskFlag] = Field(default_factory=list)


class ClientBrief(BaseModel):
    """X4 Client research: a brief built before bidding from the client's marketplace history."""
    client_id: str
    name: str = ""
    industry: str = ""
    country: str = ""
    payment_verified: bool = False
    hire_rate: float = 0.0
    avg_spend_per_hire: float = 0.0
    tenure_years: float = 0.0
    tier: Literal["new", "occasional", "established", "enterprise"] = "new"
    signals: list[str] = Field(default_factory=list)
    talking_points: list[str] = Field(default_factory=list, description="safe, specific angles for the proposal")
    sources: list[str] = Field(default_factory=list)


class RequirementMatch(BaseModel):
    requirement: str
    evidence_ids: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    strength: Literal["strong", "weak", "none"]


class FitReport(BaseModel):
    score: float = Field(ge=0, le=1)
    matrix: list[RequirementMatch] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    unsupported_requirements: list[str] = Field(default_factory=list)


class BidDecision(BaseModel):
    action: Literal["skip", "watch", "bid"]
    reasons: list[str]
    auto: bool = Field(False, description="true if taken automatically under the user's autonomy setting")


class PriceQuote(BaseModel):
    amount: float
    currency: str = "USD"
    rationale: list[str]
    market_p25: float | None = None
    market_median: float | None = None
    market_p75: float | None = None
    connects_cost: int = 0
    connects_usd: float = 0
    expected_value_usd: float = 0
    worth_it: bool = True


class Citation(BaseModel):
    sentence: str
    evidence_ids: list[str]


class ProposalDraft(BaseModel):
    cover_letter: str
    answers: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    version: int = 1
    source: Literal["llm", "rules"] = "rules"

    @property
    def word_count(self) -> int:
        return len(self.cover_letter.split())


class VerificationReport(BaseModel):
    claims: list[dict]
    unsupported_before: int
    claims_before: int
    unsupported_after: int
    claims_after: int
    changes: list[dict] = Field(default_factory=list)


class CritiqueIssue(BaseModel):
    kind: Literal["grounding", "personalisation", "length", "generic_opening", "missing_requirement", "tone",
                  "screening", "other"]
    detail: str


class Critique(BaseModel):
    passed: bool
    round: int
    issues: list[CritiqueIssue] = Field(default_factory=list)
    score: float = Field(ge=0, le=10, default=5)


class Violation(BaseModel):
    rule: str
    severity: Literal["block", "fix"]
    match: str


class ComplianceVerdict(BaseModel):
    status: Literal["pass", "fixed", "blocked"]
    violations: list[Violation] = Field(default_factory=list)
    cleaned_text: str
    cleaned_answers: list[str] = Field(default_factory=list)
    reason: str = ""


class Intent(BaseModel):
    intent: Literal["question", "negotiation", "interview_request", "scam_signal", "other"]
    confidence: float = Field(ge=0, le=1)
    notes: str = ""


class ReplyDraft(BaseModel):
    text: str
    slots: list[dict] = Field(default_factory=list)
    source: Literal["llm", "rules"] = "rules"
