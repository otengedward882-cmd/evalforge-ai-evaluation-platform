"""
Rubric management endpoints.

Rubrics define the scoring criteria applied during an evaluation run.
Each rubric belongs to a project and contains one or more criteria with
explicit scale types (BINARY, LIKERT_5, PERCENTAGE).

Endpoints:
    GET    /projects/{project_id}/rubrics
    POST   /projects/{project_id}/rubrics
    GET    /projects/{project_id}/rubrics/{rubric_id}
    POST   /projects/{project_id}/rubrics/{rubric_id}/clone
    DELETE /projects/{project_id}/rubrics/{rubric_id}
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin, require_evaluator
from app.core.database import get_db
from app.models.project import Project
from app.models.rubric import Rubric, RubricCriteria
from app.models.user import User
from app.schemas.rubric import RubricCreate, RubricResponse

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_project_or_404(project_id: str, db: Session) -> Project:
    """Return the project or raise 404."""
    project = db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    return project


def _get_rubric_or_404(rubric_id: str, project_id: str, db: Session) -> Rubric:
    """Return the rubric scoped to a project or raise 404."""
    rubric = db.scalar(
        select(Rubric).where(Rubric.id == rubric_id, Rubric.project_id == project_id)
    )
    if not rubric:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rubric not found.")
    return rubric


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/rubrics
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/rubrics",
    response_model=List[RubricResponse],
    summary="List rubrics for a project",
)
def list_rubrics(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[Rubric]:
    """Return all active rubrics for the given project (all authenticated roles)."""
    _get_project_or_404(project_id, db)
    rubrics = db.scalars(
        select(Rubric)
        .where(Rubric.project_id == project_id, Rubric.is_active == 1)
        .order_by(Rubric.created_at.desc())
    ).all()
    return list(rubrics)


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/rubrics
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/rubrics",
    response_model=RubricResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new rubric",
)
def create_rubric(
    project_id: str,
    payload: RubricCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_evaluator),
) -> Rubric:
    """
    Create a rubric with one or more scoring criteria.
    Requires at least EVALUATOR role.
    """
    _get_project_or_404(project_id, db)

    rubric = Rubric(
        project_id=project_id,
        name=payload.name,
        description=payload.description,
        created_by=current_user.id,
    )
    db.add(rubric)
    db.flush()  # Obtain rubric.id before inserting criteria

    for idx, crit_data in enumerate(payload.criteria):
        criterion = RubricCriteria(
            rubric_id=rubric.id,
            name=crit_data.name,
            description=crit_data.description,
            scale_type=crit_data.scale_type.value,
            min_score=crit_data.min_score,
            max_score=crit_data.max_score,
            weight=crit_data.weight,
            position=crit_data.position if crit_data.position != 0 else idx,
            guidelines=crit_data.guidelines,
            examples=crit_data.examples,
        )
        db.add(criterion)

    db.commit()
    db.refresh(rubric)
    return rubric


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/rubrics/{rubric_id}
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/rubrics/{rubric_id}",
    response_model=RubricResponse,
    summary="Get a single rubric with its criteria",
)
def get_rubric(
    project_id: str,
    rubric_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Rubric:
    """Return a single rubric including all its criteria (all authenticated roles)."""
    return _get_rubric_or_404(rubric_id, project_id, db)


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/rubrics/{rubric_id}/clone
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/rubrics/{rubric_id}/clone",
    response_model=RubricResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Clone a rubric as a new version",
)
def clone_rubric(
    project_id: str,
    rubric_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_evaluator),
) -> Rubric:
    """
    Create a full copy of an existing rubric with an incremented version number.
    Use this to iterate on scoring methodology without losing the original definition.
    Requires at least EVALUATOR role.
    """
    source = _get_rubric_or_404(rubric_id, project_id, db)

    # Determine next version number for this rubric name within the project
    max_version: int = db.scalar(
        select(Rubric.version)  # type: ignore[arg-type]
        .where(Rubric.project_id == project_id, Rubric.name == source.name)
        .order_by(Rubric.version.desc())
        .limit(1)
    ) or source.version
    next_version = max_version + 1

    clone = Rubric(
        project_id=project_id,
        name=source.name,
        description=source.description,
        version=next_version,
        created_by=current_user.id,
    )
    db.add(clone)
    db.flush()

    for src_crit in source.criteria:
        db.add(
            RubricCriteria(
                rubric_id=clone.id,
                name=src_crit.name,
                description=src_crit.description,
                scale_type=src_crit.scale_type,
                min_score=src_crit.min_score,
                max_score=src_crit.max_score,
                weight=src_crit.weight,
                position=src_crit.position,
                guidelines=src_crit.guidelines,
                examples=src_crit.examples,
            )
        )

    db.commit()
    db.refresh(clone)
    return clone


# ---------------------------------------------------------------------------
# DELETE /projects/{project_id}/rubrics/{rubric_id}
# ---------------------------------------------------------------------------


@router.delete(
    "/projects/{project_id}/rubrics/{rubric_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Archive (soft-delete) a rubric",
)
def archive_rubric(
    project_id: str,
    rubric_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> None:
    """
    Soft-delete a rubric by setting is_active = 0.
    The rubric remains in the database for historical evaluation runs.
    Requires ADMIN role.
    """
    rubric = _get_rubric_or_404(rubric_id, project_id, db)
    rubric.is_active = 0  # type: ignore[assignment]
    db.commit()
