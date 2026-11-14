"""
Pydantic schemas for analytics, comparative benchmarking, and reporting.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class CategoryBreakdown(BaseModel):
    category: str
    total: int
    passed: int
    failed: int
    pass_rate: float
    mean_score: Optional[float]


class DifficultyBreakdown(BaseModel):
    difficulty: str
    total: int
    passed: int
    failed: int
    pass_rate: float
    mean_score: Optional[float]


class ScorerBreakdown(BaseModel):
    scorer_name: str
    total_scored: int
    passed_count: int
    pass_rate: float
    avg_score: float


class HumanAgreementStats(BaseModel):
    total_reviewed: int
    concordant_cases: int
    discrepancy_count: int
    flagged_count: int
    agreement_rate: float


class RunAnalyticsResponse(BaseModel):
    run_id: str
    project_id: str
    status: str
    started_at: datetime
    completed_at: Optional[datetime]
    total_cases: int
    passed_cases: int
    failed_cases: int
    pass_rate: float
    mean_score: Optional[float]
    by_category: List[CategoryBreakdown]
    by_difficulty: List[DifficultyBreakdown]
    by_scorer: List[ScorerBreakdown]
    human_agreement: HumanAgreementStats


class RunCaseComparison(BaseModel):
    case_id: str
    prompt: str
    category: str
    base_passed: bool
    base_score: float
    target_passed: bool
    target_score: float
    score_delta: float


class RunComparisonResponse(BaseModel):
    base_run_id: str
    target_run_id: str
    shared_cases_count: int
    base_pass_rate: float
    target_pass_rate: float
    pass_rate_delta: float
    base_mean_score: Optional[float]
    target_mean_score: Optional[float]
    mean_score_delta: Optional[float]
    improvements_count: int
    regressions_count: int
    improvements: List[RunCaseComparison]
    regressions: List[RunCaseComparison]


class ProjectDashboardResponse(BaseModel):
    project_id: str
    project_name: str
    total_datasets: int
    total_versions: int
    total_runs: int
    total_evaluations_scored: int
    overall_pass_rate: float
    recent_runs: List[Dict[str, Any]]
