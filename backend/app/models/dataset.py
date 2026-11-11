import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship
from app.core.database import Base


class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    project = relationship("Project", back_populates="datasets")
    versions = relationship("DatasetVersion", back_populates="dataset", cascade="all, delete-orphan", order_by="desc(DatasetVersion.version_number)")

    def __repr__(self) -> str:
        return f"<Dataset id={self.id} name={self.name}>"


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    dataset_id = Column(String(36), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False)
    version_number = Column(Integer, nullable=False)
    source_format = Column(String(20), nullable=False)  # "jsonl" or "csv"
    total_records = Column(Integer, default=0, nullable=False)
    checksum_sha256 = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    dataset = relationship("Dataset", back_populates="versions")
    test_cases = relationship("TestCase", back_populates="dataset_version", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<DatasetVersion id={self.id} version={self.version_number}>"


class TestCase(Base):
    __tablename__ = "test_cases"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    dataset_version_id = Column(String(36), ForeignKey("dataset_versions.id", ondelete="CASCADE"), nullable=False)
    case_id = Column(String(100), index=True, nullable=False)
    prompt = Column(Text, nullable=False)
    expected_behavior = Column(Text, nullable=False)
    reference_answer = Column(Text, nullable=True)
    candidate_response = Column(Text, nullable=True)
    category = Column(String(100), index=True, default="General", nullable=False)
    difficulty = Column(String(50), default="Medium", nullable=False)
    metadata_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    dataset_version = relationship("DatasetVersion", back_populates="test_cases")

    def __repr__(self) -> str:
        return f"<TestCase id={self.id} case_id={self.case_id}>"
