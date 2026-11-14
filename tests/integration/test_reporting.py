"""
Integration tests for Analytics, Reporting, and Benchmarking (Milestone 8).

Covers:
- Run analytics breakdown by category, difficulty, scorer, and human concordance
- Comparative run benchmarking (A/B testing, regression and improvement detection)
- CSV stream export with automated scores and human review metadata
- Complete JSON export
- Project-wide dashboard KPIs
"""

import io
import json
import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Setup Helpers
# ---------------------------------------------------------------------------


def _bootstrap_reporting_data(client: TestClient, token: str) -> dict:
    """Creates a project, dataset with diverse test cases, and two evaluation runs."""
    # 1. Project
    proj_res = client.post(
        "/api/v1/projects",
        json={"name": "Analytics & Reporting Project", "description": "Reporting tests"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert proj_res.status_code == 201
    project_id = proj_res.json()["id"]

    # 2. Dataset
    ds_res = client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "Benchmark Dataset", "description": ""},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ds_res.status_code == 201
    dataset_id = ds_res.json()["id"]

    # 3. Version 1 (Baseline)
    cases_v1 = [
        {
            "case_id": "MATH-01",
            "prompt": "What is 10 * 10?",
            "expected_behavior": "100",
            "candidate_response": "100",
            "category": "Math",
            "difficulty": "Easy",
        },
        {
            "case_id": "MATH-02",
            "prompt": "What is square root of 49?",
            "expected_behavior": "7",
            "candidate_response": "8",  # Wrong -> will fail
            "category": "Math",
            "difficulty": "Medium",
        },
        {
            "case_id": "SCI-01",
            "prompt": "What is H2O?",
            "expected_behavior": "Water",
            "candidate_response": "Water",
            "category": "Science",
            "difficulty": "Easy",
        },
    ]
    jsonl_v1 = "\n".join(json.dumps(c) for c in cases_v1).encode("utf-8")
    up_v1 = client.post(
        f"/api/v1/projects/{project_id}/datasets/{dataset_id}/upload",
        files={"file": ("v1.jsonl", io.BytesIO(jsonl_v1), "application/octet-stream")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert up_v1.status_code == 201
    v1_id = up_v1.json()["version_id"]

    # Run 1 (Base Run)
    run1_res = client.post(
        f"/api/v1/projects/{project_id}/evaluations/run",
        json={
            "dataset_version_id": v1_id,
            "scorer_configs": [
                {
                    "scorer_name": "length",
                    "config": {"min_length": 2},
                }
            ],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert run1_res.status_code == 201
    run1_id = run1_res.json()["id"]

    # 4. Version 2 (Improved Candidate Model)
    cases_v2 = [
        {
            "case_id": "MATH-01",
            "prompt": "What is 10 * 10?",
            "expected_behavior": "100",
            "candidate_response": "100",
            "category": "Math",
            "difficulty": "Easy",
        },
        {
            "case_id": "MATH-02",
            "prompt": "What is square root of 49?",
            "expected_behavior": "7",
            "candidate_response": "49",  # Fixed length! -> will pass (improvement)
            "category": "Math",
            "difficulty": "Medium",
        },
        {
            "case_id": "SCI-01",
            "prompt": "What is H2O?",
            "expected_behavior": "Water",
            "candidate_response": "W",  # Too short! -> will fail (regression)
            "category": "Science",
            "difficulty": "Easy",
        },
    ]
    jsonl_v2 = "\n".join(json.dumps(c) for c in cases_v2).encode("utf-8")
    up_v2 = client.post(
        f"/api/v1/projects/{project_id}/datasets/{dataset_id}/upload",
        files={"file": ("v2.jsonl", io.BytesIO(jsonl_v2), "application/octet-stream")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert up_v2.status_code == 201
    v2_id = up_v2.json()["version_id"]

    # Run 2 (Target Run)
    run2_res = client.post(
        f"/api/v1/projects/{project_id}/evaluations/run",
        json={
            "dataset_version_id": v2_id,
            "scorer_configs": [
                {
                    "scorer_name": "length",
                    "config": {"min_length": 2},
                }
            ],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert run2_res.status_code == 201
    run2_id = run2_res.json()["id"]

    # Fetch test cases for V1 to submit reviews
    v1_cases_res = client.get(
        f"/api/v1/projects/{project_id}/datasets/{dataset_id}/versions/{v1_id}/cases",
        headers={"Authorization": f"Bearer {token}"},
    )
    v1_cases = v1_cases_res.json()

    return {
        "project_id": project_id,
        "dataset_id": dataset_id,
        "v1_id": v1_id,
        "v2_id": v2_id,
        "run1_id": run1_id,
        "run2_id": run2_id,
        "v1_cases": v1_cases,
    }


# ---------------------------------------------------------------------------
# Test: Detailed Run Analytics
# ---------------------------------------------------------------------------


def test_get_run_analytics(client: TestClient, admin_token: str) -> None:
    env = _bootstrap_reporting_data(client, admin_token)
    pid = env["project_id"]
    run1_id = env["run1_id"]
    case_1 = env["v1_cases"][0]["id"]
    case_2 = env["v1_cases"][1]["id"]

    # Add human review decisions for Run 1
    # Case 1: Accepted (concordant with automated pass)
    client.post(
        f"/api/v1/projects/{pid}/evaluations/{run1_id}/reviews",
        json={"test_case_id": case_1, "decision": "accepted", "feedback": "Accurate."},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    # Case 2: Flagged
    client.post(
        f"/api/v1/projects/{pid}/evaluations/{run1_id}/reviews",
        json={"test_case_id": case_2, "decision": "flagged", "feedback": "Needs review."},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    res = client.get(
        f"/api/v1/projects/{pid}/evaluations/{run1_id}/analytics",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200, res.text
    data = res.json()

    assert data["run_id"] == run1_id
    assert data["total_cases"] == 3
    assert len(data["by_category"]) >= 2
    assert len(data["by_difficulty"]) >= 2
    assert len(data["by_scorer"]) == 1

    # Human agreement check
    agr = data["human_agreement"]
    assert agr["total_reviewed"] == 2
    assert agr["flagged_count"] == 1
    assert agr["concordant_cases"] == 1


# ---------------------------------------------------------------------------
# Test: Comparative Benchmarking
# ---------------------------------------------------------------------------


def test_compare_runs(client: TestClient, admin_token: str) -> None:
    env = _bootstrap_reporting_data(client, admin_token)
    pid = env["project_id"]
    r1 = env["run1_id"]
    r2 = env["run2_id"]

    res = client.get(
        f"/api/v1/projects/{pid}/evaluations/compare",
        params={"base_run_id": r1, "target_run_id": r2},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200, res.text
    comp = res.json()

    assert comp["base_run_id"] == r1
    assert comp["target_run_id"] == r2
    assert comp["shared_cases_count"] == 3

    # Check improvement and regression identification
    # MATH-02 improved in V2 (candidate changed from 8 -> 7)
    assert comp["improvements_count"] == 1
    assert comp["improvements"][0]["case_id"] == "MATH-02"

    # SCI-01 regressed in V2 (candidate changed from Water -> Steam)
    assert comp["regressions_count"] == 1
    assert comp["regressions"][0]["case_id"] == "SCI-01"


# ---------------------------------------------------------------------------
# Test: CSV Export
# ---------------------------------------------------------------------------


def test_export_run_csv(client: TestClient, admin_token: str) -> None:
    env = _bootstrap_reporting_data(client, admin_token)
    pid = env["project_id"]
    run1_id = env["run1_id"]

    res = client.get(
        f"/api/v1/projects/{pid}/evaluations/{run1_id}/export/csv",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    assert f"evalforge_run_{run1_id[:8]}.csv" in res.headers["content-disposition"]

    csv_text = res.text
    lines = csv_text.strip().split("\n")
    assert len(lines) >= 4  # Header + 3 test cases
    assert "case_id,category,difficulty,prompt" in lines[0]
    assert "MATH-01" in csv_text
    assert "SCI-01" in csv_text


# ---------------------------------------------------------------------------
# Test: JSON Export
# ---------------------------------------------------------------------------


def test_export_run_json(client: TestClient, admin_token: str) -> None:
    env = _bootstrap_reporting_data(client, admin_token)
    pid = env["project_id"]
    run1_id = env["run1_id"]

    res = client.get(
        f"/api/v1/projects/{pid}/evaluations/{run1_id}/export/json",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    data = res.json()

    assert data["run_id"] == run1_id
    assert data["total_cases"] == 3
    assert len(data["cases"]) == 3
    assert "scores" in data["cases"][0]
    assert "reviews" in data["cases"][0]


# ---------------------------------------------------------------------------
# Test: Project Dashboard
# ---------------------------------------------------------------------------


def test_project_dashboard(client: TestClient, admin_token: str) -> None:
    env = _bootstrap_reporting_data(client, admin_token)
    pid = env["project_id"]

    res = client.get(
        f"/api/v1/projects/{pid}/dashboard",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200, res.text
    dash = res.json()

    assert dash["project_id"] == pid
    assert dash["total_datasets"] >= 1
    assert dash["total_versions"] >= 2
    assert dash["total_runs"] >= 2
    assert dash["total_evaluations_scored"] >= 6
    assert isinstance(dash["overall_pass_rate"], float)
    assert len(dash["recent_runs"]) >= 2
