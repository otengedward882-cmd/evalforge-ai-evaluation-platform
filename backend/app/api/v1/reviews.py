"""
Human review and adjudication API endpoints.

Endpoints:
    GET   /projects/{project_id}/evaluations/{run_id}/reviews/queue
        Fetch test cases formatted for review queue with automated score context.

    POST  /projects/{project_id}/evaluations/{run_id}/reviews
        Submit a human evaluation decision (accepted, rejected, flagged, overridden).

    GET   /projects/{project_id}/evaluations/{run_id}/reviews
        List all human review decisions for an evaluation run.

    GET   /projects/{project_id}/evaluations/{run_id}/reviews/{review_id}
        Get details for a specific review decision.

    PATCH /projects/{project_id}/evaluations/{run_id}/reviews/{review_id}
        Update an existing review decision (by original reviewer or admin).

    POST  /projects/{project_id}/evaluations/{run_id}/reviews/{review_id}/adjudicate
        Adjudicate and finalize a flagged or disputed decision (Admin only).
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin, require_evaluator
from app.core.database import get_db
from app.models.dataset import TestCase
from app.models.evaluation import EvaluationRun, EvaluationScore
from app.models.project import Project
from app.models.review import DecisionOutcome, ReviewDecision
from app.models.rubric import RubricCriteria
from app.models.user import User, UserRole
from app.schemas.review import (
    AdjudicationRequest,
    ReviewDecisionCreate,
    ReviewDecisionResponse,
    ReviewDecisionUpdate,
    ReviewQueueItemResponse,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_project_or_404(project_id: str, db: Session) -> Project:
    project = db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found."
        )
    return project


def _get_run_or_404(run_id: str, project_id: str, db: Session) -> EvaluationRun:
    run = db.scalar(
        select(EvaluationRun).where(
            EvaluationRun.id == run_id, EvaluationRun.project_id == project_id
        )
    )
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation run not found."
        )
    return run


def _get_review_or_404(
    review_id: str, run_id: str, project_id: str, db: Session
) -> ReviewDecision:
    review = db.scalar(
        select(ReviewDecision).where(
            ReviewDecision.id == review_id,
            ReviewDecision.run_id == run_id,
            ReviewDecision.project_id == project_id,
        )
    )
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Review decision not found."
        )
    return review


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/evaluations/{run_id}/reviews/queue
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/evaluations/{run_id}/reviews/queue",
    response_model=List[ReviewQueueItemResponse],
    summary="Get test cases for human review queue",
)
def get_review_queue(
    project_id: str,
    run_id: str,
    unreviewed_only: bool = Query(False, description="Filter for cases with 0 reviews"),
    flagged_only: bool = Query(False, description="Filter for cases with flagged decisions"),
    disputed_only: bool = Query(
        False, description="Filter for failing automated checks or conflicting reviews"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[ReviewQueueItemResponse]:
    """
    Returns items in the evaluation run formatted for reviewer triage and evaluation.
    """
    _get_project_or_404(project_id, db)
    run = _get_run_or_404(run_id, project_id, db)

    # 1. Fetch test cases for this dataset version
    test_cases = list(
        db.scalars(
            select(TestCase).where(TestCase.dataset_version_id == run.dataset_version_id)
        ).all()
    )

    # 2. Fetch all scores for this run
    scores = list(
        db.scalars(
            select(EvaluationScore).where(EvaluationScore.run_id == run_id)
        ).all()
    )
    scores_by_case: dict[str, list[EvaluationScore]] = {}
    for s in scores:
        scores_by_case.setdefault(s.test_case_id, []).append(s)

    # 3. Fetch existing reviews for this run
    reviews = list(
        db.scalars(
            select(ReviewDecision).where(ReviewDecision.run_id == run_id)
        ).all()
    )
    reviews_by_case: dict[str, list[ReviewDecision]] = {}
    for r in reviews:
        reviews_by_case.setdefault(r.test_case_id, []).append(r)

    # 4. Construct queue items with filtering
    queue: List[ReviewQueueItemResponse] = []
    for tc in test_cases:
        case_scores = scores_by_case.get(tc.id, [])
        automated_passed = (
            all(bool(s.passed) for s in case_scores) if case_scores else False
        )
        case_reviews = reviews_by_case.get(tc.id, [])
        reviews_count = len(case_reviews)
        is_flagged = any(
            r.decision == DecisionOutcome.FLAGGED.value for r in case_reviews
        )

        # Apply filters
        if unreviewed_only and reviews_count > 0:
            continue
        if flagged_only and not is_flagged:
            continue
        if disputed_only:
            # Conflicting reviews or automated failure with accepted human review
            has_accepted = any(
                r.decision == DecisionOutcome.ACCEPTED.value for r in case_reviews
            )
            has_rejected = any(
                r.decision == DecisionOutcome.REJECTED.value for r in case_reviews
            )
            is_disputed = (
                is_flagged
                or (has_accepted and has_rejected)
                or (not automated_passed and has_accepted)
            )
            if not is_disputed:
                continue

        queue.append(
            ReviewQueueItemResponse(
                test_case_id=tc.id,
                case_id=tc.case_id,
                prompt=tc.prompt,
                expected_behavior=tc.expected_behavior,
                candidate_response=tc.candidate_response,
                automated_passed=automated_passed,
                automated_scores=[
                    {
                        "scorer_name": s.scorer_name,
                        "passed": s.passed,
                        "score": s.score,
                        "reason": s.reason,
                    }
                    for s in case_scores
                ],
                reviews_count=reviews_count,
                is_flagged=is_flagged,
            )
        )

    return queue[skip : skip + limit]


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/evaluations/{run_id}/reviews
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/evaluations/{run_id}/reviews",
    response_model=ReviewDecisionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a human review decision",
)
def create_review(
    project_id: str,
    run_id: str,
    payload: ReviewDecisionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_evaluator),
) -> ReviewDecision:
    """
    Submits a human evaluation decision for a test case within an evaluation run.
    Requires at least EVALUATOR role.
    """
    _get_project_or_404(project_id, db)
    run = _get_run_or_404(run_id, project_id, db)

    # Verify test_case belongs to this dataset version
    test_case = db.scalar(
        select(TestCase).where(
            TestCase.id == payload.test_case_id,
            TestCase.dataset_version_id == run.dataset_version_id,
        )
    )
    if not test_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="TestCase not found in this evaluation run's dataset version.",
        )

    # If criterion_id is provided, verify it belongs to this project
    if payload.criterion_id:
        crit = db.scalar(
            select(RubricCriteria).where(RubricCriteria.id == payload.criterion_id)
        )
        if not crit:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rubric criterion not found.",
            )

    review = ReviewDecision(
        project_id=project_id,
        run_id=run_id,
        test_case_id=payload.test_case_id,
        reviewer_id=current_user.id,
        criterion_id=payload.criterion_id,
        decision=payload.decision.value,
        human_score=payload.human_score,
        feedback=payload.feedback,
        is_adjudicated=1 if payload.decision != DecisionOutcome.FLAGGED else 0,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/evaluations/{run_id}/reviews
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/evaluations/{run_id}/reviews",
    response_model=List[ReviewDecisionResponse],
    summary="List all reviews for an evaluation run",
)
def list_reviews(
    project_id: str,
    run_id: str,
    decision: Optional[str] = Query(None, description="Filter by decision enum"),
    test_case_id: Optional[str] = Query(None, description="Filter by test case UUID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[ReviewDecision]:
    _get_project_or_404(project_id, db)
    _get_run_or_404(run_id, project_id, db)

    query = select(ReviewDecision).where(
        ReviewDecision.run_id == run_id,
        ReviewDecision.project_id == project_id,
    )
    if decision:
        query = query.where(ReviewDecision.decision == decision)
    if test_case_id:
        query = query.where(ReviewDecision.test_case_id == test_case_id)

    query = query.order_by(ReviewDecision.created_at.desc()).offset(skip).limit(limit)
    reviews = db.scalars(query).all()
    return list(reviews)


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/evaluations/{run_id}/reviews/{review_id}
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/evaluations/{run_id}/reviews/{review_id}",
    response_model=ReviewDecisionResponse,
    summary="Get single review decision",
)
def get_review(
    project_id: str,
    run_id: str,
    review_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReviewDecision:
    _get_project_or_404(project_id, db)
    _get_run_or_404(run_id, project_id, db)
    return _get_review_or_404(review_id, run_id, project_id, db)


# ---------------------------------------------------------------------------
# PATCH /projects/{project_id}/evaluations/{run_id}/reviews/{review_id}
# ---------------------------------------------------------------------------


@router.patch(
    "/projects/{project_id}/evaluations/{run_id}/reviews/{review_id}",
    response_model=ReviewDecisionResponse,
    summary="Update an existing review decision",
)
def update_review(
    project_id: str,
    run_id: str,
    review_id: str,
    payload: ReviewDecisionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_evaluator),
) -> ReviewDecision:
    """
    Updates an existing review. Reviewers can update their own reviews; Admins can update any review.
    """
    _get_project_or_404(project_id, db)
    _get_run_or_404(run_id, project_id, db)
    review = _get_review_or_404(review_id, run_id, project_id, db)

    # Permission check: author or admin
    if review.reviewer_id != current_user.id and current_user.role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own review decisions unless you are an administrator.",
        )

    if payload.decision is not None:
        review.decision = payload.decision.value  # type: ignore[assignment]
        if payload.decision == DecisionOutcome.FLAGGED:
            review.is_adjudicated = 0  # type: ignore[assignment]
    if payload.human_score is not None:
        review.human_score = payload.human_score  # type: ignore[assignment]
    if payload.feedback is not None:
        review.feedback = payload.feedback  # type: ignore[assignment]

    db.commit()
    db.refresh(review)
    return review


# ---------------------------------------------------------------------------
# POST /projects/{project_id}/evaluations/{run_id}/reviews/{review_id}/adjudicate
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/evaluations/{run_id}/reviews/{review_id}/adjudicate",
    response_model=ReviewDecisionResponse,
    summary="Adjudicate a flagged or disputed review decision",
)
def adjudicate_review(
    project_id: str,
    run_id: str,
    review_id: str,
    payload: AdjudicationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> ReviewDecision:
    """
    Finalizes an adjudicated outcome for a flagged or disputed review.
    Restricted to ADMINISTRATOR role.
    """
    _get_project_or_404(project_id, db)
    _get_run_or_404(run_id, project_id, db)
    review = _get_review_or_404(review_id, run_id, project_id, db)

    review.decision = payload.decision.value  # type: ignore[assignment]
    if payload.human_score is not None:
        review.human_score = payload.human_score  # type: ignore[assignment]
    review.adjudication_notes = payload.adjudication_notes  # type: ignore[assignment]
    review.adjudicated_by = current_user.id  # type: ignore[assignment]
    review.is_adjudicated = 1  # type: ignore[assignment]

    db.commit()
    db.refresh(review)
    return review
