from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class EvidenceType(str, Enum):
    OBSERVED = "observed"
    CALCULATED = "calculated"
    ESTIMATED = "estimated"
    QUALITATIVE = "qualitative"


class SourceTier(int, Enum):
    TIER1 = 1
    TIER2 = 2
    TIER3 = 3
    TIER4 = 4


class Skill(BaseModel):
    skill_id: str
    skill_name: str
    category: str
    description: str = ""


class Source(BaseModel):
    source_id: str = ""
    organization: str = ""
    title: str = ""
    url: str = ""
    publication_date: str = ""
    source_tier: int = 4
    methodology: str = ""
    retrieved_at: str = ""


class Evidence(BaseModel):
    evidence_id: str = ""
    source_id: str = ""
    skill_id: str = ""
    metric: str = ""
    value: Optional[float] = None
    unit: str = ""
    period: str = ""
    geography: str = ""
    industry: str = ""
    evidence_type: EvidenceType = EvidenceType.QUALITATIVE
    retrieved_at: str = ""


class DailyScore(BaseModel):
    date: str
    skill_id: str
    demand_score: float = 0.0
    growth_rate: Optional[float] = None
    emerging_score: float = 0.0
    confidence: str = "low"


class RunRecord(BaseModel):
    run_id: str
    started_at: str
    completed_at: str = ""
    sources_checked: int = 0
    sources_accepted: int = 0
    sources_rejected: int = 0
    records_processed: int = 0
    skills_tracked: int = 0
    errors: list[str] = Field(default_factory=list)


class TrendResult(BaseModel):
    skill_id: str
    skill_name: str
    yoy_growth: Optional[float] = None
    mom_growth: Optional[float] = None
    rolling_12m_change: Optional[float] = None
    skill_share: Optional[float] = None
    share_change: Optional[float] = None
    emerging_score: float = 0.0
    confidence: str = "low"
    evidence_type: EvidenceType = EvidenceType.QUALITATIVE


class DashboardData(BaseModel):
    generated_at: str
    total_skills: int
    emerging_skills: int
    increasing_skills: int
    declining_skills: int
    new_evidence_items: int
    sources_analyzed: int
    industries_tracked: int
    countries_tracked: int
    trends: list[TrendResult] = Field(default_factory=list)
    monthly_data: list[dict] = Field(default_factory=list)
    industry_comparison: list[dict] = Field(default_factory=list)
    new_skills_detected: list[str] = Field(default_factory=list)
    evidence_confidence: dict = Field(default_factory=dict)
