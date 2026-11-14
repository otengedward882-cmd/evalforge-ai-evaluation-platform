"""
Human review and adjudication models for EvalForge.

Captures qualitative human evaluation, score overrides, feedback notes,
flagging for adjudication, and resolution by leads or admins.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class DecisionOutcome(str, enum.Enum):
    ACCEPTED = "accepted"       # Approves the model output / automated scoring
    REJECTED = "rejected"       # Rejects the model output
    FLAGGED = "flagged"         # Flags for senior review / adjudication
    OVERRIDDEN = "overridden"   # Provides a custom human score override


class ReviewDecision(Base):
    __tablename__ = "review_decisions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    run_id = Column(
        String(36), ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False
    )
    test_case_id = Column(
        String(36), ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False
    )
    reviewer_id = Column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    criterion_id = Column(
        String(36), ForeignKey("rubric_criteria.id", ondelete="SET NULL"), nullable=True
    )
    decision = Column(
        String(30), default=DecisionOutcome.ACCEPTED.value, nullable=False
    )
    human_score = Column(Float, nullable=True)
    feedback = Column(Text, nullable=False)

    # Adjudication fields
    is_adjudicated = Column(Integer, default=0, nullable=False)  # 0 = no/pending, 1 = completed
    adjudicated_by = Column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    adjudication_notes = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    project = relationship("Project", backref="review_decisions")
    run = relationship("EvaluationRun", backref="review_decisions")
    test_case = relationship("TestCase", backref="review_decisions")
    reviewer = relationship("User", foreign_keys=[reviewer_id], backref="reviews_submitted")
    adjudicator = relationship("User", foreign_keys=[adjudicated_by], backref="reviews_adjudicated")
    criterion = relationship("RubricCriteria", backref="review_decisions")

    def __repr__(self) -> str:
        return (
            f"<ReviewDecision id={self.id} run={self.run_id} "
            f"case={self.test_case_id} decision={self.decision}>"
        )
