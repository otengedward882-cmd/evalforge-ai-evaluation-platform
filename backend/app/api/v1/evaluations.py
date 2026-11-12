"""
Evaluation engine API endpoints.

POST   /projects/{project_id}/evaluations/run
    Trigger a synchronous evaluation run against a dataset version.

GET    /projects/{project_id}/evaluations
    List all evaluation runs for a project.

GET    /projects/{project_id}/evaluations/{run_id}
    Get a single run with aggregate statistics.

GET    /projects/{project_id}/evaluations/{run_id}/scores
    Get all individual scores for a run (paginated).

Design note
-----------
Runs execute synchronously within the HTTP request for the MVP scope.
The status transitions: PENDING → RUNNING → COMPLETED | FAILED.
Each test_case in the dataset version is scored against every configured scorer.
Aggregate stats (mean_score, passed_cases) are computed after all scoring.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_evaluator
from app.core.database import get_db
from app.engine.scorers import get_scorer
from app.models.dataset import Dataset as DatasetModel, DatasetVersion, TestCase
from app.models.evaluation import EvaluationRun, EvaluationScore, RunStatus
from app.models.project import Project
from app.models.rubric import Rubric
from app.models.user import User
from app.schemas.evaluation import (
    EvaluationRunCreate,
    EvaluationRunResponse,
    EvaluationRunSummary,
    EvaluationScoreResponse,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_project_or_404(project_id: str, db: Session) -> Project:
    project = db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    return project


def _get_run_or_404(run_id: str, project_id: str, db: Session) -> EvaluationRun:
    run = db.scalar(
        select(EvaluationRun).where(
            EvaluationRun.id == run_id,
            EvaluationRun.project_id == project_id,
        )
    )
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation run not found.")
    return run


def _run_evaluation(
    run: EvaluationRun,
    test_cases: List[TestCase],
    scorer_configs: List[dict],
    db: Session,
) -> None:
    """
    Execute all scorers against every test case and persist EvaluationScore rows.
    Updates run aggregate statistics in-place.
    """
    run.status = RunStatus.RUNNING.value  # type: ignore[assignment]
    db.flush()

    all_scores: List[EvaluationScore] = []

    for test_case in test_cases:
        # 'candidate_response' holds the AI-generated text to evaluate.
        # If absent (e.g. format-only checks), fall back to the prompt text.
        response_text: str = (
            test_case.candidate_response  # type: ignore[attr-defined]
            if test_case.candidate_response  # type: ignore[attr-defined]
            else (test_case.prompt or "")  # type: ignore[attr-defined]
        )

        for sc in scorer_configs:
            scorer_name: str = sc.get("scorer_name", "")
            config: dict = sc.get("config", {})

            try:
                scorer = get_scorer(scorer_name)
                result = scorer.score(response=response_text, config=config)
            except Exception as exc:
                # Scorer-level error — record as failure, continue
                result_dict = {
                    "passed": False,
                    "score": 0.0,
                    "reason": f"Scorer error: {exc}",
                    "details": {},
                }
                score_row = EvaluationScore(
                    run_id=run.id,
                    test_case_id=test_case.id,
                    scorer_name=scorer_name or "unknown",
                    passed=0,
                    score=0.0,
                    reason=result_dict["reason"],
                    details={},
                )
                all_scores.append(score_row)
                db.add(score_row)
                continue

            score_row = EvaluationScore(
                run_id=run.id,
                test_case_id=test_case.id,
                scorer_name=scorer_name,
                passed=1 if result.passed else 0,
                score=result.score,
                reason=result.reason,
                details=result.details,
            )
            all_scores.append(score_row)
            db.add(score_row)

    # Aggregate stats
    run.total_cases = len(test_cases)  # type: ignore[assignment]
    if all_scores:
        # A test case passes if ALL its scorer results pass
        case_results: dict[str, list[bool]] = {}
        for s in all_scores:
            case_results.setdefault(s.test_case_id, []).append(bool(s.passed))

        passed_cases = sum(1 for results in case_results.values() if all(results))
        run.passed_cases = passed_cases  # type: ignore[assignment]
        run.failed_cases = run.total_cases - passed_cases  # type: ignore[assignment]
        run.mean_score = round(  # type: ignore[assignment]
            sum(s.score for s in all_scores) / len(all_scores), 4
        )
    else:
        run.passed_cases = 0  # type: ignore[assignment]
        run.failed_cases = 0  # type: ignore[assignment]
        run.mean_score = None  # type: ignore[assignment]

    run.status = RunStatus.COMPLETED.value  # type: ignore[assignment]
    run.completed_at = datetime.now(timezone.utc)  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/evaluations/run
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/evaluations/run",
    response_model=EvaluationRunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Trigger an evaluation run",
)
def trigger_evaluation_run(
    project_id: str,
    payload: EvaluationRunCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_evaluator),
) -> EvaluationRun:
    """
    Execute a synchronous evaluation run.

    For each test case in the dataset version, every configured scorer is applied
    to the test case's `actual_response` field.

    Returns the completed run with aggregate statistics.
    """
    _get_project_or_404(project_id, db)

    # Validate dataset version belongs to this project via a joined query
    dv = db.scalar(
        select(DatasetVersion)
        .join(DatasetModel, DatasetVersion.dataset_id == DatasetModel.id)
        .where(
            DatasetVersion.id == payload.dataset_version_id,
            DatasetModel.project_id == project_id,
        )
    )
    if not dv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset version not found."
        )

    # Validate rubric if provided
    if payload.rubric_id:
        rubric = db.scalar(
            select(Rubric).where(
                Rubric.id == payload.rubric_id, Rubric.project_id == project_id
            )
        )
        if not rubric:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rubric not found in this project.",
            )

    # Validate all scorer names before starting
    for sc in payload.scorer_configs:
        try:
            get_scorer(sc.scorer_name)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc

    # Fetch test cases
    test_cases = list(
        db.scalars(
            select(TestCase).where(TestCase.dataset_version_id == payload.dataset_version_id)
        ).all()
    )
    if not test_cases:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Dataset version contains no test cases.",
        )

    # Create run record
    run = EvaluationRun(
        project_id=project_id,
        dataset_version_id=payload.dataset_version_id,
        rubric_id=payload.rubric_id,
        scorer_configs=[sc.model_dump() for sc in payload.scorer_configs],
        started_by=current_user.id,
    )
    db.add(run)
    db.flush()

    # Execute evaluation
    try:
        _run_evaluation(
            run=run,
            test_cases=test_cases,
            scorer_configs=[sc.model_dump() for sc in payload.scorer_configs],
            db=db,
        )
        db.commit()
        db.refresh(run)
    except Exception as exc:
        run.status = RunStatus.FAILED.value  # type: ignore[assignment]
        run.error_message = str(exc)  # type: ignore[assignment]
        run.completed_at = datetime.now(timezone.utc)  # type: ignore[assignment]
        db.commit()
        db.refresh(run)

    return run


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/evaluations
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/evaluations",
    response_model=List[EvaluationRunSummary],
    summary="List evaluation runs for a project",
)
def list_evaluation_runs(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[EvaluationRun]:
    _get_project_or_404(project_id, db)
    runs = db.scalars(
        select(EvaluationRun)
        .where(EvaluationRun.project_id == project_id)
        .order_by(EvaluationRun.started_at.desc())
    ).all()
    return list(runs)


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/evaluations/{run_id}
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/evaluations/{run_id}",
    response_model=EvaluationRunResponse,
    summary="Get evaluation run details",
)
def get_evaluation_run(
    project_id: str,
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EvaluationRun:
    return _get_run_or_404(run_id, project_id, db)


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/evaluations/{run_id}/scores
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/evaluations/{run_id}/scores",
    response_model=List[EvaluationScoreResponse],
    summary="Get individual scores for an evaluation run",
)
def list_evaluation_scores(
    project_id: str,
    run_id: str,
    scorer_name: Optional[str] = Query(None, description="Filter by scorer name"),
    passed: Optional[bool] = Query(None, description="Filter by pass/fail"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[EvaluationScore]:
    _get_run_or_404(run_id, project_id, db)

    query = select(EvaluationScore).where(EvaluationScore.run_id == run_id)

    if scorer_name:
        query = query.where(EvaluationScore.scorer_name == scorer_name)
    if passed is not None:
        query = query.where(EvaluationScore.passed == (1 if passed else 0))

    query = query.order_by(EvaluationScore.scored_at).offset(skip).limit(limit)
    scores = db.scalars(query).all()
    return list(scores)
