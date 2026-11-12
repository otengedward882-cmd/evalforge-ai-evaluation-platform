"""
Pydantic schemas for evaluation runs and scores.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Scorer configuration (embedded in EvaluationRunCreate)
# ---------------------------------------------------------------------------


class ScorerConfigItem(BaseModel):
    """One scorer entry in a run's scorer_configs list."""

    scorer_name: str = Field(..., description="Registered scorer name, e.g. 'exact_match'")
    config: Dict[str, Any] = Field(default_factory=dict, description="Scorer-specific parameters")
    weight: float = Field(1.0, ge=0.0, description="Relative weight for aggregate scoring")


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class EvaluationRunCreate(BaseModel):
    dataset_version_id: str = Field(..., description="UUID of the DatasetVersion to evaluate")
    rubric_id: Optional[str] = Field(None, description="Optional rubric UUID to associate")
    scorer_configs: List[ScorerConfigItem] = Field(
        ..., min_length=1, description="At least one scorer must be specified"
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class EvaluationScoreResponse(BaseModel):
    id: str
    run_id: str
    test_case_id: str
    scorer_name: str
    passed: int
    score: float
    reason: str
    details: Dict[str, Any]
    scored_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EvaluationRunResponse(BaseModel):
    id: str
    project_id: str
    dataset_version_id: str
    rubric_id: Optional[str]
    scorer_configs: List[Dict[str, Any]]
    status: str
    started_by: str
    started_at: datetime
    completed_at: Optional[datetime]
    total_cases: int
    passed_cases: int
    failed_cases: int
    mean_score: Optional[float]
    error_message: Optional[str]

    model_config = ConfigDict(from_attributes=True)


class EvaluationRunSummary(BaseModel):
    """Lightweight list item — no score details."""

    id: str
    status: str
    total_cases: int
    passed_cases: int
    mean_score: Optional[float]
    started_at: datetime
    completed_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)
