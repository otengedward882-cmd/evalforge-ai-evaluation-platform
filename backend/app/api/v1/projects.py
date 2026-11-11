import re
from typing import List, Optional
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session
from app.api.deps import get_current_user, require_evaluator
from app.core.database import get_db
from app.engine.dataset_parser import DatasetValidationError, parse_and_validate_dataset
from app.models.dataset import Dataset, DatasetVersion, TestCase
from app.models.project import Project
from app.models.user import User
from app.schemas.dataset import (
    DatasetCreate,
    DatasetResponse,
    DatasetVersionResponse,
    ImportResultResponse,
    TestCaseResponse,
)
from app.schemas.project import ProjectCreate, ProjectResponse, ProjectUpdate

router = APIRouter(prefix="/projects", tags=["Projects & Datasets"])


def slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    return slug.strip("-")


# --- Projects CRUD ---

@router.get("", response_model=List[ProjectResponse])
def list_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lists all evaluation projects."""
    return db.query(Project).order_by(Project.created_at.desc()).all()


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    project_in: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_evaluator)
):
    """Creates a new evaluation project."""
    slug = project_in.slug or slugify(project_in.name)

    # Ensure unique slug
    base_slug = slug
    counter = 1
    while db.query(Project).filter(Project.slug == slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1

    project = Project(
        name=project_in.name,
        slug=slug,
        description=project_in.description,
        created_by=current_user.id
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieves a single project by ID."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    return project


# --- Datasets & Versions ---

@router.get("/{project_id}/datasets", response_model=List[DatasetResponse])
def list_datasets(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lists all datasets belonging to a project."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    datasets = db.query(Dataset).filter(Dataset.project_id == project_id).all()
    # Attach latest version metadata if present
    results = []
    for d in datasets:
        latest = d.versions[0] if d.versions else None
        res = DatasetResponse.model_validate(d)
        res.latest_version = DatasetVersionResponse.model_validate(latest) if latest else None
        results.append(res)
    return results


@router.post("/{project_id}/datasets", response_model=DatasetResponse, status_code=status.HTTP_201_CREATED)
def create_dataset(
    project_id: str,
    dataset_in: DatasetCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_evaluator)
):
    """Creates a new dataset container inside a project."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )

    dataset = Dataset(
        project_id=project_id,
        name=dataset_in.name,
        description=dataset_in.description
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return dataset


@router.post("/{project_id}/datasets/{dataset_id}/upload", response_model=ImportResultResponse)
async def upload_dataset_version(
    project_id: str,
    dataset_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_evaluator)
):
    """
    Uploads a CSV or JSONL dataset file.
    Validates required fields, checks for duplicates, and creates a versioned test suite.
    """
    dataset = db.query(Dataset).filter(
        Dataset.id == dataset_id,
        Dataset.project_id == project_id
    ).first()
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found in this project"
        )

    content = await file.read()
    try:
        parse_result = parse_and_validate_dataset(content, file.filename or "data.jsonl")
    except DatasetValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    if not parse_result.is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Dataset validation failed. See row errors.",
                "total_rows": parse_result.total_rows_processed,
                "errors": parse_result.errors
            }
        )

    # Determine next version number
    current_versions = db.query(DatasetVersion).filter(
        DatasetVersion.dataset_id == dataset_id
    ).count()
    next_version = current_versions + 1

    source_fmt = "jsonl" if file.filename and file.filename.lower().endswith(".jsonl") else "csv"

    # Create DatasetVersion
    version = DatasetVersion(
        dataset_id=dataset_id,
        version_number=next_version,
        source_format=source_fmt,
        total_records=len(parse_result.records),
        checksum_sha256=parse_result.checksum_sha256
    )
    db.add(version)
    db.flush()  # Flush to acquire version.id

    # Bulk insert test cases
    test_cases_to_insert = [
        TestCase(
            dataset_version_id=version.id,
            case_id=r["case_id"],
            prompt=r["prompt"],
            expected_behavior=r["expected_behavior"],
            reference_answer=r["reference_answer"],
            candidate_response=r["candidate_response"],
            category=r["category"],
            difficulty=r["difficulty"],
            metadata_json=r["metadata_json"]
        )
        for r in parse_result.records
    ]
    db.bulk_save_objects(test_cases_to_insert)
    db.commit()

    return ImportResultResponse(
        success=True,
        dataset_id=dataset_id,
        version_number=next_version,
        total_imported=len(test_cases_to_insert),
        checksum_sha256=parse_result.checksum_sha256,
        errors=[]
    )


@router.get("/{project_id}/datasets/{dataset_id}/versions/{version_id}/cases", response_model=List[TestCaseResponse])
def get_dataset_version_cases(
    project_id: str,
    dataset_id: str,
    version_id: str,
    category: Optional[str] = Query(None, description="Filter by category"),
    search: Optional[str] = Query(None, description="Search prompt or case_id"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieves paginated test cases belonging to a specific dataset version."""
    version = db.query(DatasetVersion).join(Dataset).filter(
        DatasetVersion.id == version_id,
        Dataset.id == dataset_id,
        Dataset.project_id == project_id
    ).first()
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset version not found"
        )

    query = db.query(TestCase).filter(TestCase.dataset_version_id == version_id)
    if category:
        query = query.filter(TestCase.category == category)
    if search:
        query = query.filter(
            (TestCase.prompt.ilike(f"%{search}%")) | (TestCase.case_id.ilike(f"%{search}%"))
        )

    return query.order_by(TestCase.case_id).offset(skip).limit(limit).all()
