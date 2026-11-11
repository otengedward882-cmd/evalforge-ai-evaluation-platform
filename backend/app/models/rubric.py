import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship
from app.core.database import Base


class ScaleType(str, enum.Enum):
    BINARY = "binary"          # 0 or 1 (Pass/Fail)
    LIKERT_5 = "likert_5"      # 1 to 5 integer scale
    PERCENTAGE = "percentage"  # 0.0 to 1.0 continuous


class Rubric(Base):
    __tablename__ = "rubrics"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    version = Column(Integer, default=1, nullable=False)
    is_active = Column(Integer, default=1, nullable=False)  # 1 = active, 0 = archived
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    project = relationship("Project", backref="rubrics")
    creator = relationship("User", backref="rubrics")
    criteria = relationship("RubricCriteria", back_populates="rubric", cascade="all, delete-orphan", order_by="RubricCriteria.position")

    def __repr__(self) -> str:
        return f"<Rubric id={self.id} name={self.name} version={self.version}>"


class RubricCriteria(Base):
    __tablename__ = "rubric_criteria"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    rubric_id = Column(String(36), ForeignKey("rubrics.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    scale_type = Column(String(20), default=ScaleType.LIKERT_5.value, nullable=False)
    min_score = Column(Float, default=1.0, nullable=False)
    max_score = Column(Float, default=5.0, nullable=False)
    weight = Column(Float, default=1.0, nullable=False)   # Relative weighting for aggregated scores
    position = Column(Integer, default=0, nullable=False)  # Display order
    guidelines = Column(JSON, default=dict, nullable=False)  # {score: description} anchors
    examples = Column(JSON, default=dict, nullable=False)   # {"pass": "...", "fail": "..."}

    # Relationships
    rubric = relationship("Rubric", back_populates="criteria")

    def __repr__(self) -> str:
        return f"<RubricCriteria id={self.id} name={self.name} scale={self.scale_type}>"
