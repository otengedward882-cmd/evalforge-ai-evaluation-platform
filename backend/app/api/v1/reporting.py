"""
Analytics, comparative benchmarking, and export API endpoints.

Endpoints:
    GET /projects/{project_id}/evaluations/{run_id}/analytics
        Aggregated run performance by category, difficulty, scorer, and human concordance.

    GET /projects/{project_id}/evaluations/compare
        Comparative benchmarking between two evaluation runs (A/B testing, regression analysis).

    GET /projects/{project_id}/evaluations/{run_id}/export/csv
        Export complete evaluation run with scores and human reviews to CSV.

    GET /projects/{project_id}/evaluations/{run_id}/export/json
        Export complete evaluation run with scores and human reviews to JSON.

    GET /projects/{project_id}/dashboard
        High-level project KPIs, dataset counts, historical pass rates, and recent run activity.
"""

from __future__ import annotations

import csv
import io
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.dataset import Dataset, DatasetVersion, TestCase
from app.models.evaluation import EvaluationRun, EvaluationScore
from app.models.project import Project
from app.models.review import DecisionOutcome, ReviewDecision
from app.models.user import User
from app.schemas.reporting import (
    CategoryBreakdown,
    DifficultyBreakdown,
    HumanAgreementStats,
    ProjectDashboardResponse,
    RunAnalyticsResponse,
    RunCaseComparison,
    RunComparisonResponse,
    ScorerBreakdown,
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


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/evaluations/{run_id}/analytics
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/evaluations/{run_id}/analytics",
    response_model=RunAnalyticsResponse,
    summary="Get detailed evaluation run analytics",
)
def get_run_analytics(
    project_id: str,
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RunAnalyticsResponse:
    """
    Computes multifaceted performance statistics for an evaluation run:
    - Pass rate & mean score broken down by Category
    - Pass rate & mean score broken down by Difficulty
    - Accuracy & average score per individual Scorer
    - Human-to-automated concordance (agreement vs. discrepancy)
    """
    _get_project_or_404(project_id, db)
    run = _get_run_or_404(run_id, project_id, db)

    # 1. Fetch test cases
    test_cases = list(
        db.scalars(
            select(TestCase).where(TestCase.dataset_version_id == run.dataset_version_id)
        ).all()
    )

    # 2. Fetch scores
    scores = list(
        db.scalars(
            select(EvaluationScore).where(EvaluationScore.run_id == run_id)
        ).all()
    )
    scores_by_case: dict[str, list[EvaluationScore]] = {}
    for s in scores:
        scores_by_case.setdefault(s.test_case_id, []).append(s)

    # 3. Fetch reviews
    reviews = list(
        db.scalars(
            select(ReviewDecision).where(ReviewDecision.run_id == run_id)
        ).all()
    )
    reviews_by_case: dict[str, list[ReviewDecision]] = {}
    for r in reviews:
        reviews_by_case.setdefault(r.test_case_id, []).append(r)

    # Compute overall pass rate
    total_cases = len(test_cases)
    pass_rate = (
        round((run.passed_cases / total_cases) * 100, 2) if total_cases > 0 else 0.0
    )

    # Group by category & difficulty
    cat_map: dict[str, dict[str, Any]] = {}
    diff_map: dict[str, dict[str, Any]] = {}

    for tc in test_cases:
        case_scores = scores_by_case.get(tc.id, [])
        passed = all(bool(s.passed) for s in case_scores) if case_scores else False
        avg_score = (
            sum(s.score for s in case_scores) / len(case_scores)
            if case_scores
            else 0.0
        )

        # Category
        cat = tc.category or "General"
        if cat not in cat_map:
            cat_map[cat] = {"total": 0, "passed": 0, "scores": []}
        cat_map[cat]["total"] += 1
        if passed:
            cat_map[cat]["passed"] += 1
        cat_map[cat]["scores"].append(avg_score)

        # Difficulty
        diff = tc.difficulty or "Medium"
        if diff not in diff_map:
            diff_map[diff] = {"total": 0, "passed": 0, "scores": []}
        diff_map[diff]["total"] += 1
        if passed:
            diff_map[diff]["passed"] += 1
        diff_map[diff]["scores"].append(avg_score)

    by_category = [
        CategoryBreakdown(
            category=cat,
            total=data["total"],
            passed=data["passed"],
            failed=data["total"] - data["passed"],
            pass_rate=round((data["passed"] / data["total"]) * 100, 2),
            mean_score=round(sum(data["scores"]) / len(data["scores"]), 4)
            if data["scores"]
            else None,
        )
        for cat, data in cat_map.items()
    ]

    by_difficulty = [
        DifficultyBreakdown(
            difficulty=diff,
            total=data["total"],
            passed=data["passed"],
            failed=data["total"] - data["passed"],
            pass_rate=round((data["passed"] / data["total"]) * 100, 2),
            mean_score=round(sum(data["scores"]) / len(data["scores"]), 4)
            if data["scores"]
            else None,
        )
        for diff, data in diff_map.items()
    ]

    # Scorer breakdown
    scorer_stats: dict[str, dict[str, Any]] = {}
    for s in scores:
        if s.scorer_name not in scorer_stats:
            scorer_stats[s.scorer_name] = {"total": 0, "passed": 0, "scores": []}
        scorer_stats[s.scorer_name]["total"] += 1
        if s.passed:
            scorer_stats[s.scorer_name]["passed"] += 1
        scorer_stats[s.scorer_name]["scores"].append(s.score)

    by_scorer = [
        ScorerBreakdown(
            scorer_name=name,
            total_scored=data["total"],
            passed_count=data["passed"],
            pass_rate=round((data["passed"] / data["total"]) * 100, 2),
            avg_score=round(sum(data["scores"]) / len(data["scores"]), 4)
            if data["scores"]
            else 0.0,
        )
        for name, data in scorer_stats.items()
    ]

    # Human agreement metrics
    reviewed_cases = [tc for tc in test_cases if tc.id in reviews_by_case]
    total_reviewed = len(reviewed_cases)
    concordant_count = 0
    flagged_count = 0

    for tc in reviewed_cases:
        case_scores = scores_by_case.get(tc.id, [])
        auto_passed = all(bool(s.passed) for s in case_scores) if case_scores else False
        case_revs = reviews_by_case[tc.id]

        is_flagged = any(r.decision == DecisionOutcome.FLAGGED.value for r in case_revs)
        if is_flagged:
            flagged_count += 1
            continue

        human_positive = any(
            r.decision == DecisionOutcome.ACCEPTED.value
            or (
                r.decision == DecisionOutcome.OVERRIDDEN.value
                and (r.human_score is None or r.human_score >= 0.5)
            )
            for r in case_revs
        )

        if auto_passed == human_positive:
            concordant_count += 1

    discrepancy_count = total_reviewed - concordant_count - flagged_count
    agreement_rate = (
        round((concordant_count / total_reviewed) * 100, 2)
        if total_reviewed > 0
        else 100.0
    )

    human_agreement = HumanAgreementStats(
        total_reviewed=total_reviewed,
        concordant_cases=concordant_count,
        discrepancy_count=max(0, discrepancy_count),
        flagged_count=flagged_count,
        agreement_rate=agreement_rate,
    )

    return RunAnalyticsResponse(
        run_id=run.id,
        project_id=project_id,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        total_cases=run.total_cases,
        passed_cases=run.passed_cases,
        failed_cases=run.failed_cases,
        pass_rate=pass_rate,
        mean_score=run.mean_score,
        by_category=by_category,
        by_difficulty=by_difficulty,
        by_scorer=by_scorer,
        human_agreement=human_agreement,
    )


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/evaluations/compare
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/evaluations/compare",
    response_model=RunComparisonResponse,
    summary="Compare two evaluation runs (A/B testing, regression analysis)",
)
def compare_runs(
    project_id: str,
    base_run_id: str = Query(..., description="Baseline evaluation run UUID"),
    target_run_id: str = Query(..., description="Target / candidate evaluation run UUID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RunComparisonResponse:
    """
    Compares two evaluation runs by aligning shared test cases:
    - Calculates pass rate and mean score deltas
    - Identifies regressions (passed in baseline, failed in target)
    - Identifies improvements (failed in baseline, passed in target)
    """
    _get_project_or_404(project_id, db)
    base_run = _get_run_or_404(base_run_id, project_id, db)
    target_run = _get_run_or_404(target_run_id, project_id, db)

    # Fetch test cases & scores for base run
    base_cases = {
        tc.case_id: tc
        for tc in db.scalars(
            select(TestCase).where(TestCase.dataset_version_id == base_run.dataset_version_id)
        ).all()
    }
    base_scores = list(
        db.scalars(
            select(EvaluationScore).where(EvaluationScore.run_id == base_run_id)
        ).all()
    )
    base_scores_by_case: dict[str, list[EvaluationScore]] = {}
    for s in base_scores:
        base_scores_by_case.setdefault(s.test_case_id, []).append(s)

    # Fetch test cases & scores for target run
    target_cases = {
        tc.case_id: tc
        for tc in db.scalars(
            select(TestCase).where(TestCase.dataset_version_id == target_run.dataset_version_id)
        ).all()
    }
    target_scores = list(
        db.scalars(
            select(EvaluationScore).where(EvaluationScore.run_id == target_run_id)
        ).all()
    )
    target_scores_by_case: dict[str, list[EvaluationScore]] = {}
    for s in target_scores:
        target_scores_by_case.setdefault(s.test_case_id, []).append(s)

    # Find shared case IDs
    shared_case_ids = set(base_cases.keys()).intersection(set(target_cases.keys()))

    improvements: List[RunCaseComparison] = []
    regressions: List[RunCaseComparison] = []

    for cid in sorted(shared_case_ids):
        b_tc = base_cases[cid]
        t_tc = target_cases[cid]

        b_sc = base_scores_by_case.get(b_tc.id, [])
        t_sc = target_scores_by_case.get(t_tc.id, [])

        b_passed = all(bool(s.passed) for s in b_sc) if b_sc else False
        t_passed = all(bool(s.passed) for s in t_sc) if t_sc else False

        b_score = (
            round(sum(s.score for s in b_sc) / len(b_sc), 4) if b_sc else 0.0
        )
        t_score = (
            round(sum(s.score for s in t_sc) / len(t_sc), 4) if t_sc else 0.0
        )
        score_delta = round(t_score - b_score, 4)

        comparison = RunCaseComparison(
            case_id=cid,
            prompt=t_tc.prompt,
            category=t_tc.category or "General",
            base_passed=b_passed,
            base_score=b_score,
            target_passed=t_passed,
            target_score=t_score,
            score_delta=score_delta,
        )

        if not b_passed and t_passed:
            improvements.append(comparison)
        elif b_passed and not t_passed:
            regressions.append(comparison)

    base_pr = (
        round((base_run.passed_cases / base_run.total_cases) * 100, 2)
        if base_run.total_cases > 0
        else 0.0
    )
    target_pr = (
        round((target_run.passed_cases / target_run.total_cases) * 100, 2)
        if target_run.total_cases > 0
        else 0.0
    )
    pr_delta = round(target_pr - base_pr, 2)

    base_ms = base_run.mean_score
    target_ms = target_run.mean_score
    ms_delta = (
        round(target_ms - base_ms, 4)
        if (target_ms is not None and base_ms is not None)
        else None
    )

    return RunComparisonResponse(
        base_run_id=base_run_id,
        target_run_id=target_run_id,
        shared_cases_count=len(shared_case_ids),
        base_pass_rate=base_pr,
        target_pass_rate=target_pr,
        pass_rate_delta=pr_delta,
        base_mean_score=base_ms,
        target_mean_score=target_ms,
        mean_score_delta=ms_delta,
        improvements_count=len(improvements),
        regressions_count=len(regressions),
        improvements=improvements,
        regressions=regressions,
    )


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/evaluations/{run_id}/export/csv
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/evaluations/{run_id}/export/csv",
    summary="Export evaluation run results to CSV",
)
def export_run_csv(
    project_id: str,
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """
    Generates a full CSV export containing test cases, automated scorer outcomes,
    and qualitative human review decisions.
    """
    _get_project_or_404(project_id, db)
    run = _get_run_or_404(run_id, project_id, db)

    test_cases = list(
        db.scalars(
            select(TestCase).where(TestCase.dataset_version_id == run.dataset_version_id)
        ).all()
    )

    scores = list(
        db.scalars(
            select(EvaluationScore).where(EvaluationScore.run_id == run_id)
        ).all()
    )
    scores_by_case: dict[str, list[EvaluationScore]] = {}
    for s in scores:
        scores_by_case.setdefault(s.test_case_id, []).append(s)

    reviews = list(
        db.scalars(
            select(ReviewDecision).where(ReviewDecision.run_id == run_id)
        ).all()
    )
    reviews_by_case: dict[str, list[ReviewDecision]] = {}
    for r in reviews:
        reviews_by_case.setdefault(r.test_case_id, []).append(r)

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow(
        [
            "case_id",
            "category",
            "difficulty",
            "prompt",
            "expected_behavior",
            "candidate_response",
            "automated_passed",
            "mean_score",
            "scorers_summary",
            "human_decision",
            "human_score",
            "human_feedback",
            "is_adjudicated",
        ]
    )

    for tc in test_cases:
        case_scores = scores_by_case.get(tc.id, [])
        auto_passed = (
            all(bool(s.passed) for s in case_scores) if case_scores else False
        )
        avg_score = (
            round(sum(s.score for s in case_scores) / len(case_scores), 4)
            if case_scores
            else 0.0
        )
        scorers_summary = "; ".join(
            f"{s.scorer_name}:{'PASS' if s.passed else 'FAIL'}({s.score})"
            for s in case_scores
        )

        case_revs = reviews_by_case.get(tc.id, [])
        latest_rev = case_revs[0] if case_revs else None
        human_decision = latest_rev.decision if latest_rev else ""
        human_score = latest_rev.human_score if latest_rev and latest_rev.human_score is not None else ""
        human_feedback = latest_rev.feedback if latest_rev else ""
        is_adjudicated = latest_rev.is_adjudicated if latest_rev else ""

        writer.writerow(
            [
                tc.case_id,
                tc.category,
                tc.difficulty,
                tc.prompt,
                tc.expected_behavior,
                tc.candidate_response or "",
                "PASS" if auto_passed else "FAIL",
                avg_score,
                scorers_summary,
                human_decision,
                human_score,
                human_feedback,
                is_adjudicated,
            ]
        )

    output.seek(0)
    filename = f"evalforge_run_{run_id[:8]}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/evaluations/{run_id}/export/json
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/evaluations/{run_id}/export/json",
    summary="Export complete evaluation run to JSON",
)
def export_run_json(
    project_id: str,
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Exports a comprehensive JSON payload of the evaluation run, including
    dataset version information, automated scores, and review histories.
    """
    _get_project_or_404(project_id, db)
    run = _get_run_or_404(run_id, project_id, db)

    test_cases = list(
        db.scalars(
            select(TestCase).where(TestCase.dataset_version_id == run.dataset_version_id)
        ).all()
    )

    scores = list(
        db.scalars(
            select(EvaluationScore).where(EvaluationScore.run_id == run_id)
        ).all()
    )
    scores_by_case: dict[str, list[EvaluationScore]] = {}
    for s in scores:
        scores_by_case.setdefault(s.test_case_id, []).append(s)

    reviews = list(
        db.scalars(
            select(ReviewDecision).where(ReviewDecision.run_id == run_id)
        ).all()
    )
    reviews_by_case: dict[str, list[ReviewDecision]] = {}
    for r in reviews:
        reviews_by_case.setdefault(r.test_case_id, []).append(r)

    cases_export = []
    for tc in test_cases:
        case_scores = scores_by_case.get(tc.id, [])
        case_revs = reviews_by_case.get(tc.id, [])
        cases_export.append(
            {
                "case_id": tc.case_id,
                "category": tc.category,
                "difficulty": tc.difficulty,
                "prompt": tc.prompt,
                "expected_behavior": tc.expected_behavior,
                "candidate_response": tc.candidate_response,
                "automated_passed": all(bool(s.passed) for s in case_scores) if case_scores else False,
                "scores": [
                    {
                        "scorer_name": s.scorer_name,
                        "passed": bool(s.passed),
                        "score": s.score,
                        "reason": s.reason,
                        "details": s.details,
                    }
                    for s in case_scores
                ],
                "reviews": [
                    {
                        "decision": r.decision,
                        "human_score": r.human_score,
                        "feedback": r.feedback,
                        "is_adjudicated": bool(r.is_adjudicated),
                        "adjudication_notes": r.adjudication_notes,
                    }
                    for r in case_revs
                ],
            }
        )

    return {
        "run_id": run.id,
        "project_id": project_id,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "total_cases": run.total_cases,
        "passed_cases": run.passed_cases,
        "failed_cases": run.failed_cases,
        "mean_score": run.mean_score,
        "scorer_configs": run.scorer_configs,
        "cases": cases_export,
    }


# ---------------------------------------------------------------------------
# GET /projects/{project_id}/dashboard
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/dashboard",
    response_model=ProjectDashboardResponse,
    summary="Get project-wide overview dashboard metrics",
)
def get_project_dashboard(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectDashboardResponse:
    """
    High-level project summary: dataset count, versions, run count,
    overall pass rate, and recent execution feed.
    """
    project = _get_project_or_404(project_id, db)

    total_datasets = db.scalar(
        select(func.count(Dataset.id)).where(Dataset.project_id == project_id)
    ) or 0

    total_versions = db.scalar(
        select(func.count(DatasetVersion.id))
        .join(Dataset, DatasetVersion.dataset_id == Dataset.id)
        .where(Dataset.project_id == project_id)
    ) or 0

    runs = list(
        db.scalars(
            select(EvaluationRun)
            .where(EvaluationRun.project_id == project_id)
            .order_by(EvaluationRun.started_at.desc())
        ).all()
    )
    total_runs = len(runs)

    total_cases = sum(r.total_cases for r in runs)
    total_passed = sum(r.passed_cases for r in runs)
    overall_pass_rate = (
        round((total_passed / total_cases) * 100, 2) if total_cases > 0 else 0.0
    )

    recent_runs = [
        {
            "id": r.id,
            "status": r.status,
            "total_cases": r.total_cases,
            "passed_cases": r.passed_cases,
            "mean_score": r.mean_score,
            "started_at": r.started_at.isoformat() if r.started_at else None,
        }
        for r in runs[:5]
    ]

    return ProjectDashboardResponse(
        project_id=project.id,
        project_name=project.name,
        total_datasets=total_datasets,
        total_versions=total_versions,
        total_runs=total_runs,
        total_evaluations_scored=total_cases,
        overall_pass_rate=overall_pass_rate,
        recent_runs=recent_runs,
    )
