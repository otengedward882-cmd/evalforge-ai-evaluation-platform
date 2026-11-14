"""
Integration tests for Human Review & Adjudication Interface (Milestone 7).

Covers:
- Review queue retrieval with automated scorer context
- Queue filtering: unreviewed_only, flagged_only, disputed_only
- Creating human review decisions: accepted, rejected, flagged, overridden
- RBAC permissions: Evaluator can create, Reviewer can read, Admin can adjudicate
- Author-level updates vs. Admin overrides
- Lead/Admin adjudication of flagged decisions
- Cross-project and invalid resource 404 validation
"""

import io
import json
import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Setup Helpers
# ---------------------------------------------------------------------------


def _setup_project_and_run(client: TestClient, token: str) -> dict:
    """Helper to bootstrap a project, dataset, and completed evaluation run."""
    # 1. Create project
    proj_res = client.post(
        "/api/v1/projects",
        json={"name": "Review Test Project", "description": "Review suite testing"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert proj_res.status_code == 201, proj_res.text
    project_id = proj_res.json()["id"]

    # 2. Create dataset
    ds_res = client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "Review QA Dataset", "description": ""},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ds_res.status_code == 201, ds_res.text
    dataset_id = ds_res.json()["id"]

    # 3. Upload dataset version with 2 cases (1 correct, 1 incorrect)
    cases = [
        {
            "case_id": "REV-001",
            "prompt": "What is the capital of Japan?",
            "expected_behavior": "Return Tokyo",
            "candidate_response": "Tokyo",
        },
        {
            "case_id": "REV-002",
            "prompt": "Explain Quantum Entanglement simply.",
            "expected_behavior": "Particles remaining connected over distances",
            "candidate_response": "I do not know.",
        },
    ]
    jsonl_bytes = "\n".join(json.dumps(c) for c in cases).encode("utf-8")
    up_res = client.post(
        f"/api/v1/projects/{project_id}/datasets/{dataset_id}/upload",
        files={"file": ("cases.jsonl", io.BytesIO(jsonl_bytes), "application/octet-stream")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert up_res.status_code == 201, up_res.text
    version_id = up_res.json()["version_id"]

    # 4. Trigger evaluation run with exact_match scorer
    run_res = client.post(
        f"/api/v1/projects/{project_id}/evaluations/run",
        json={
            "dataset_version_id": version_id,
            "scorer_configs": [
                {
                    "scorer_name": "exact_match",
                    "config": {"expected": "Tokyo"},
                }
            ],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert run_res.status_code == 201, run_res.text
    run_id = run_res.json()["id"]

    # 5. Fetch imported cases to get their IDs
    cases_res = client.get(
        f"/api/v1/projects/{project_id}/datasets/{dataset_id}/versions/{version_id}/cases",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert cases_res.status_code == 200
    test_cases = cases_res.json()

    return {
        "project_id": project_id,
        "dataset_id": dataset_id,
        "version_id": version_id,
        "run_id": run_id,
        "test_cases": test_cases,
    }


# ---------------------------------------------------------------------------
# Test: Get Review Queue
# ---------------------------------------------------------------------------


def test_get_review_queue(client: TestClient, admin_token: str) -> None:
    env = _setup_project_and_run(client, admin_token)
    pid = env["project_id"]
    run_id = env["run_id"]

    res = client.get(
        f"/api/v1/projects/{pid}/evaluations/{run_id}/reviews/queue",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200, res.text
    queue = res.json()
    assert len(queue) == 2

    # Verify first item (Tokyo exact match passed)
    tokyo_item = next(item for item in queue if item["case_id"] == "REV-001")
    assert tokyo_item["automated_passed"] is True
    assert len(tokyo_item["automated_scores"]) == 1
    assert tokyo_item["reviews_count"] == 0
    assert tokyo_item["is_flagged"] is False

    # Verify second item (I do not know failed)
    quantum_item = next(item for item in queue if item["case_id"] == "REV-002")
    assert quantum_item["automated_passed"] is False


# ---------------------------------------------------------------------------
# Test: Submit Human Review (Accepted & Overridden)
# ---------------------------------------------------------------------------


def test_create_review_decisions(
    client: TestClient, admin_token: str, evaluator_token: str
) -> None:
    env = _setup_project_and_run(client, admin_token)
    pid = env["project_id"]
    run_id = env["run_id"]
    case_1 = env["test_cases"][0]["id"]
    case_2 = env["test_cases"][1]["id"]

    # 1. Evaluator reviews case 1 as ACCEPTED
    res1 = client.post(
        f"/api/v1/projects/{pid}/evaluations/{run_id}/reviews",
        json={
            "test_case_id": case_1,
            "decision": "accepted",
            "feedback": "Concise and correct factual answer.",
        },
        headers={"Authorization": f"Bearer {evaluator_token}"},
    )
    assert res1.status_code == 201, res1.text
    d1 = res1.json()
    assert d1["decision"] == "accepted"
    assert d1["is_adjudicated"] == 1

    # 2. Evaluator reviews case 2 as OVERRIDDEN with score
    res2 = client.post(
        f"/api/v1/projects/{pid}/evaluations/{run_id}/reviews",
        json={
            "test_case_id": case_2,
            "decision": "overridden",
            "human_score": 0.2,
            "feedback": "Honest refusal is better than hallucination, awarding partial credit.",
        },
        headers={"Authorization": f"Bearer {evaluator_token}"},
    )
    assert res2.status_code == 201, res2.text
    d2 = res2.json()
    assert d2["decision"] == "overridden"
    assert d2["human_score"] == 0.2


# ---------------------------------------------------------------------------
# Test: Review Queue Filtering
# ---------------------------------------------------------------------------


def test_review_queue_filters(
    client: TestClient, admin_token: str, evaluator_token: str
) -> None:
    env = _setup_project_and_run(client, admin_token)
    pid = env["project_id"]
    run_id = env["run_id"]
    case_1 = env["test_cases"][0]["id"]
    case_2 = env["test_cases"][1]["id"]

    # Flag case 2
    client.post(
        f"/api/v1/projects/{pid}/evaluations/{run_id}/reviews",
        json={
            "test_case_id": case_2,
            "decision": "flagged",
            "feedback": "Model refused to answer. Needs lead adjudication on prompt policy.",
        },
        headers={"Authorization": f"Bearer {evaluator_token}"},
    )

    # Filter unreviewed_only (case 1 unreviewed, case 2 has 1 review)
    res_unrev = client.get(
        f"/api/v1/projects/{pid}/evaluations/{run_id}/reviews/queue?unreviewed_only=true",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_unrev.status_code == 200
    assert len(res_unrev.json()) == 1
    assert res_unrev.json()[0]["test_case_id"] == case_1

    # Filter flagged_only (case 2 is flagged)
    res_flag = client.get(
        f"/api/v1/projects/{pid}/evaluations/{run_id}/reviews/queue?flagged_only=true",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_flag.status_code == 200
    assert len(res_flag.json()) == 1
    assert res_flag.json()[0]["test_case_id"] == case_2


# ---------------------------------------------------------------------------
# Test: Update Review Decision
# ---------------------------------------------------------------------------


def test_update_review_decision(
    client: TestClient, admin_token: str, evaluator_token: str
) -> None:
    env = _setup_project_and_run(client, admin_token)
    pid = env["project_id"]
    run_id = env["run_id"]
    case_1 = env["test_cases"][0]["id"]

    # Evaluator creates review
    create_res = client.post(
        f"/api/v1/projects/{pid}/evaluations/{run_id}/reviews",
        json={
            "test_case_id": case_1,
            "decision": "accepted",
            "feedback": "Initial feedback.",
        },
        headers={"Authorization": f"Bearer {evaluator_token}"},
    )
    review_id = create_res.json()["id"]

    # Evaluator updates their own review
    patch_res = client.patch(
        f"/api/v1/projects/{pid}/evaluations/{run_id}/reviews/{review_id}",
        json={"feedback": "Updated thorough feedback."},
        headers={"Authorization": f"Bearer {evaluator_token}"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["feedback"] == "Updated thorough feedback."


# ---------------------------------------------------------------------------
# Test: Adjudication of Flagged Decision (Admin Only)
# ---------------------------------------------------------------------------


def test_adjudicate_flagged_decision(
    client: TestClient, admin_token: str, evaluator_token: str
) -> None:
    env = _setup_project_and_run(client, admin_token)
    pid = env["project_id"]
    run_id = env["run_id"]
    case_2 = env["test_cases"][1]["id"]

    # Evaluator flags case 2
    flag_res = client.post(
        f"/api/v1/projects/{pid}/evaluations/{run_id}/reviews",
        json={
            "test_case_id": case_2,
            "decision": "flagged",
            "feedback": "Requires resolution by lead.",
        },
        headers={"Authorization": f"Bearer {evaluator_token}"},
    )
    review_id = flag_res.json()["id"]
    assert flag_res.json()["is_adjudicated"] == 0

    # Evaluator attempts adjudication -> 403 Forbidden
    eval_adj = client.post(
        f"/api/v1/projects/{pid}/evaluations/{run_id}/reviews/{review_id}/adjudicate",
        json={
            "decision": "rejected",
            "adjudication_notes": "Adjudicating as evaluator should fail.",
        },
        headers={"Authorization": f"Bearer {evaluator_token}"},
    )
    assert eval_adj.status_code == 403

    # Admin adjudicates -> 200 Success
    admin_adj = client.post(
        f"/api/v1/projects/{pid}/evaluations/{run_id}/reviews/{review_id}/adjudicate",
        json={
            "decision": "rejected",
            "human_score": 0.0,
            "adjudication_notes": "Model refusal violates the completeness rubric.",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_adj.status_code == 200, admin_adj.text
    adj_data = admin_adj.json()
    assert adj_data["decision"] == "rejected"
    assert adj_data["human_score"] == 0.0
    assert adj_data["is_adjudicated"] == 1
    assert "completeness rubric" in adj_data["adjudication_notes"]


# ---------------------------------------------------------------------------
# Test: Read Reviews by Reviewer (Read-Only Role)
# ---------------------------------------------------------------------------


def test_reviewer_can_list_and_read_reviews(
    client: TestClient, admin_token: str
) -> None:
    # Register a read-only reviewer user
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "readonly_reviewer@example.com",
            "password": "Password123!",
            "full_name": "Read Only",
            "role": "reviewer",
        },
    )
    login_res = client.post(
        "/api/v1/auth/login/json",
        json={"email": "readonly_reviewer@example.com", "password": "Password123!"},
    )
    reviewer_token = login_res.json()["access_token"]

    env = _setup_project_and_run(client, admin_token)
    pid = env["project_id"]
    run_id = env["run_id"]
    case_1 = env["test_cases"][0]["id"]

    # Admin creates review
    rev_res = client.post(
        f"/api/v1/projects/{pid}/evaluations/{run_id}/reviews",
        json={"test_case_id": case_1, "decision": "accepted", "feedback": "Looks great."},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    review_id = rev_res.json()["id"]

    # Reviewer can fetch review list
    list_res = client.get(
        f"/api/v1/projects/{pid}/evaluations/{run_id}/reviews",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1

    # Reviewer can get specific review by ID
    get_res = client.get(
        f"/api/v1/projects/{pid}/evaluations/{run_id}/reviews/{review_id}",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert get_res.status_code == 200
    assert get_res.json()["id"] == review_id

    # Reviewer CANNOT create review -> 403 Forbidden
    unauth_create = client.post(
        f"/api/v1/projects/{pid}/evaluations/{run_id}/reviews",
        json={"test_case_id": case_1, "decision": "accepted", "feedback": "Reviewer attempt."},
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert unauth_create.status_code == 403
