"""
Evaluation run and scoring models.

EvaluationRun   — a single execution that pairs a dataset version with
                  an optional rubric, scorer configurations, and captures
                  aggregate statistics once complete.

EvaluationScore — one scored record per (test_case × scorer), linked to
                  the parent run.
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class RunStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    dataset_version_id = Column(
        String(36), ForeignKey("dataset_versions.id", ondelete="RESTRICT"), nullable=False
    )
    rubric_id = Column(
        String(36), ForeignKey("rubrics.id", ondelete="SET NULL"), nullable=True
    )
    # Scorer configuration: list of {scorer_name, config, weight}
    scorer_configs = Column(JSON, nullable=False, default=list)
    status = Column(String(20), default=RunStatus.PENDING.value, nullable=False)
    started_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    started_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Aggregate stats (populated on completion)
    total_cases = Column(Integer, default=0)
    passed_cases = Column(Integer, default=0)
    failed_cases = Column(Integer, default=0)
    mean_score = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)  # Set if status=FAILED

    # Relationships
    project = relationship("Project", backref="evaluation_runs")
    dataset_version = relationship("DatasetVersion", backref="evaluation_runs")
    rubric = relationship("Rubric", backref="evaluation_runs")
    runner = relationship("User", backref="evaluation_runs")
    scores = relationship(
        "EvaluationScore",
        back_populates="run",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<EvaluationRun id={self.id} status={self.status}>"


class EvaluationScore(Base):
    __tablename__ = "evaluation_scores"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(
        String(36), ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False
    )
    test_case_id = Column(
        String(36), ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False
    )
    scorer_name = Column(String(60), nullable=False)
    passed = Column(Integer, nullable=False)   # 1 = pass, 0 = fail
    score = Column(Float, nullable=False)      # 0.0 – 1.0 normalised
    reason = Column(Text, nullable=False)
    details = Column(JSON, default=dict)
    scored_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    run = relationship("EvaluationRun", back_populates="scores")
    test_case = relationship("TestCase", backref="scores")

    def __repr__(self) -> str:
        return (
            f"<EvaluationScore run={self.run_id} "
            f"case={self.test_case_id} scorer={self.scorer_name} "
            f"score={self.score}>"
        )
