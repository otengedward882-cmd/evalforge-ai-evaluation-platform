"""
Pydantic schemas for human review and adjudication.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.review import DecisionOutcome


class ReviewDecisionCreate(BaseModel):
    test_case_id: str = Field(..., description="UUID of the TestCase being reviewed")
    criterion_id: Optional[str] = Field(None, description="Optional RubricCriteria UUID")
    decision: DecisionOutcome = Field(
        default=DecisionOutcome.ACCEPTED,
        description="Review outcome: accepted, rejected, flagged, or overridden",
    )
    human_score: Optional[float] = Field(
        None, ge=0.0, le=100.0, description="Optional human assigned score"
    )
    feedback: str = Field(
        ..., min_length=3, description="Reviewer feedback and justification"
    )


class ReviewDecisionUpdate(BaseModel):
    decision: Optional[DecisionOutcome] = None
    human_score: Optional[float] = Field(None, ge=0.0, le=100.0)
    feedback: Optional[str] = Field(None, min_length=3)


class AdjudicationRequest(BaseModel):
    decision: DecisionOutcome = Field(
        ..., description="Final resolution decision after adjudication"
    )
    human_score: Optional[float] = Field(
        None, ge=0.0, le=100.0, description="Final adjudicated score"
    )
    adjudication_notes: str = Field(
        ..., min_length=5, description="Lead/Admin justification for final adjudication"
    )


class ReviewDecisionResponse(BaseModel):
    id: str
    project_id: str
    run_id: str
    test_case_id: str
    reviewer_id: str
    criterion_id: Optional[str]
    decision: str
    human_score: Optional[float]
    feedback: str
    is_adjudicated: int
    adjudicated_by: Optional[str]
    adjudication_notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReviewQueueItemResponse(BaseModel):
    test_case_id: str
    case_id: str
    prompt: str
    expected_behavior: str
    candidate_response: Optional[str]
    automated_passed: bool
    automated_scores: List[Dict[str, Any]]
    reviews_count: int
    is_flagged: bool

    model_config = ConfigDict(from_attributes=True)
