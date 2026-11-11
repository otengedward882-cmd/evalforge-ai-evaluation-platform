from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class DatasetBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = None


class DatasetCreate(DatasetBase):
    pass


class TestCaseResponse(BaseModel):
    id: str
    dataset_version_id: str
    case_id: str
    prompt: str
    expected_behavior: str
    reference_answer: Optional[str] = None
    candidate_response: Optional[str] = None
    category: str
    difficulty: str
    metadata_json: Dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DatasetVersionResponse(BaseModel):
    id: str
    dataset_id: str
    version_number: int
    source_format: str
    total_records: int
    checksum_sha256: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DatasetResponse(DatasetBase):
    id: str
    project_id: str
    created_at: datetime
    latest_version: Optional[DatasetVersionResponse] = None

    model_config = ConfigDict(from_attributes=True)


class ImportResultResponse(BaseModel):
    success: bool
    dataset_id: str
    version_number: int
    total_imported: int
    checksum_sha256: str
    errors: List[Dict[str, Any]]
