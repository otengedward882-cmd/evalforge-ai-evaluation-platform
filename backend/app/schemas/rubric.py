from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.models.rubric import ScaleType


class RubricCriteriaCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: str = Field(..., min_length=10)
    scale_type: ScaleType = ScaleType.LIKERT_5
    min_score: float = Field(1.0, ge=0.0)
    max_score: float = Field(5.0, le=100.0)
    weight: float = Field(1.0, ge=0.1, le=10.0)
    position: int = Field(0, ge=0)
    guidelines: Dict[str, str] = Field(default_factory=dict)
    examples: Dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_scale_boundaries(self) -> "RubricCriteriaCreate":
        if self.scale_type == ScaleType.BINARY:
            self.min_score = 0.0
            self.max_score = 1.0
        elif self.scale_type == ScaleType.LIKERT_5:
            if not (1.0 <= self.min_score and self.max_score <= 5.0):
                raise ValueError("Likert scale must be between 1 and 5.")
        elif self.scale_type == ScaleType.PERCENTAGE:
            if not (0.0 <= self.min_score and self.max_score <= 1.0):
                raise ValueError("Percentage scale must be between 0.0 and 1.0.")
        if self.min_score >= self.max_score:
            raise ValueError("min_score must be strictly less than max_score.")
        return self


class RubricCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = None
    criteria: List[RubricCriteriaCreate] = Field(..., min_length=1)


class RubricCriteriaResponse(BaseModel):
    id: str
    rubric_id: str
    name: str
    description: str
    scale_type: str
    min_score: float
    max_score: float
    weight: float
    position: int
    guidelines: Dict[str, Any]
    examples: Dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


class RubricResponse(BaseModel):
    id: str
    project_id: str
    name: str
    description: Optional[str]
    version: int
    is_active: int
    created_by: str
    created_at: datetime
    criteria: List[RubricCriteriaResponse] = []

    model_config = ConfigDict(from_attributes=True)
