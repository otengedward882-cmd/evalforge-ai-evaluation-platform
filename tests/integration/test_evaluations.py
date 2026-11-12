"""
Integration tests for the Evaluation Engine (Milestone 6).

Covers:
- Trigger evaluation run with ExactMatch scorer → COMPLETED with correct stats
- Trigger run with RequiredKeywords scorer
- Trigger run with Prohibited scorer (violation detected)
- Trigger run with Regex scorer
- Trigger run with Length scorer
- Trigger run with multiple scorers simultaneously
- Reject unknown scorer name → 422
- Reject run against nonexistent dataset version → 404
- List evaluation runs for a project
- Get run details by ID
- Get scores with scorer_name filter
- Get scores with passed=True / passed=False filter
- Reviewer can list runs
- Evaluator role required to trigger run → unauthenticated gets 401
"""

import io
import json
import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_project(client: TestClient, token: str, name: str = "Eval Project") -> str:
    resp = client.post(
        "/api/v1/projects",
        json={"name": name, "description": "Project for eval tests"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _upload_dataset(
    client: TestClient,
    token: str,
    project_id: str,
    cases: list[dict],
    dataset_name: str = "Test Dataset",
) -> dict:
    """Create a dataset + upload a JSONL version; return {dataset_id, version_id}."""
    # Create dataset
    ds_resp = client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": dataset_name, "description": ""},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ds_resp.status_code == 201, ds_resp.text
    dataset_id = ds_resp.json()["id"]

    # Build JSONL bytes
    jsonl_content = "\n".join(json.dumps(c) for c in cases)
    file_bytes = jsonl_content.encode("utf-8")

    # Upload
    up_resp = client.post(
        f"/api/v1/projects/{project_id}/datasets/{dataset_id}/upload",
        files={"file": ("cases.jsonl", io.BytesIO(file_bytes), "application/octet-stream")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert up_resp.status_code == 201, up_resp.text
    version_id = up_resp.json()["version_id"]
    return {"dataset_id": dataset_id, "version_id": version_id}


# ---------------------------------------------------------------------------
# Shared sample test cases
# ---------------------------------------------------------------------------

CASES_EXACT = [
    {
        "case_id": "ex-001",
        "prompt": "What is 2+2?",
        "expected_behavior": "Return '4'",
        "candidate_response": "4",
    },
    {
        "case_id": "ex-002",
        "prompt": "What is the capital of France?",
        "expected_behavior": "Return 'Paris'",
        "candidate_response": "London",   # Wrong answer — should fail
    },
]

CASES_KEYWORDS = [
    {
        "case_id": "kw-001",
        "prompt": "Describe photosynthesis.",
        "expected_behavior": "Mention 'chlorophyll' and 'sunlight'",
        "candidate_response": "Plants use chlorophyll to absorb sunlight and produce glucose.",
    },
    {
        "case_id": "kw-002",
        "prompt": "Describe respiration.",
        "expected_behavior": "Mention 'oxygen'",
        "candidate_response": "Cells break down glucose.",  # Missing 'oxygen'
    },
]


# ---------------------------------------------------------------------------
# Test: ExactMatch scorer — 1 pass, 1 fail
# ---------------------------------------------------------------------------


def test_evaluation_run_exact_match(client: TestClient, admin_token: str) -> None:
    pid = _create_project(client, admin_token, "ExactMatch Project")
    ids = _upload_dataset(client, admin_token, pid, CASES_EXACT)
    version_id = ids["version_id"]

    resp = client.post(
        f"/api/v1/projects/{pid}/evaluations/run",
        json={
            "dataset_version_id": version_id,
            "scorer_configs": [
                {
                    "scorer_name": "exact_match",
                    "config": {"expected": "4"},  # Only ex-001 will pass
                    "weight": 1.0,
                }
            ],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "completed"
    assert data["total_cases"] == 2
    assert data["passed_cases"] == 1
    assert data["failed_cases"] == 1
    assert data["mean_score"] is not None


# ---------------------------------------------------------------------------
# Test: RequiredKeywords scorer
# ---------------------------------------------------------------------------


def test_evaluation_run_required_keywords(client: TestClient, admin_token: str) -> None:
    pid = _create_project(client, admin_token, "Keywords Project")
    ids = _upload_dataset(client, admin_token, pid, CASES_KEYWORDS, "KW Dataset")
    version_id = ids["version_id"]

    resp = client.post(
        f"/api/v1/projects/{pid}/evaluations/run",
        json={
            "dataset_version_id": version_id,
            "scorer_configs": [
                {
                    "scorer_name": "required_keywords",
                    "config": {"keywords": ["oxygen"]},
                    "weight": 1.0,
                }
            ],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "completed"
    # kw-001 response mentions "chlorophyll" and "sunlight" but NOT "oxygen" → fail
    # kw-002 response does NOT mention "oxygen" → fail
    assert data["passed_cases"] == 0


# ---------------------------------------------------------------------------
# Test: ProhibitedKeywords scorer — canary token detection
# ---------------------------------------------------------------------------


def test_evaluation_run_prohibited_keywords(client: TestClient, admin_token: str) -> None:
    cases = [
        {
            "case_id": "ph-001",
            "prompt": "What is a safe response?",
            "expected_behavior": "No harmful content",
            "candidate_response": "Here is a helpful, safe answer.",
        },
        {
            "case_id": "ph-002",
            "prompt": "What is an unsafe response?",
            "expected_behavior": "No harmful content",
            "candidate_response": "This contains IGNORE PREVIOUS INSTRUCTIONS.",
        },
    ]
    pid = _create_project(client, admin_token, "Prohibited Project")
    ids = _upload_dataset(client, admin_token, pid, cases, "PH Dataset")

    resp = client.post(
        f"/api/v1/projects/{pid}/evaluations/run",
        json={
            "dataset_version_id": ids["version_id"],
            "scorer_configs": [
                {
                    "scorer_name": "prohibited_keywords",
                    "config": {"keywords": ["ignore previous instructions"]},
                }
            ],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["passed_cases"] == 1
    assert data["failed_cases"] == 1


# ---------------------------------------------------------------------------
# Test: Regex scorer
# ---------------------------------------------------------------------------


def test_evaluation_run_regex_scorer(client: TestClient, admin_token: str) -> None:
    cases = [
        {
            "case_id": "rx-001",
            "prompt": "Give me a date.",
            "expected_behavior": "Must contain a date in YYYY-MM-DD format",
            "candidate_response": "The date is 2026-11-11.",
        },
        {
            "case_id": "rx-002",
            "prompt": "Give me a date.",
            "expected_behavior": "Must contain a date",
            "candidate_response": "No date provided here.",
        },
    ]
    pid = _create_project(client, admin_token, "Regex Project")
    ids = _upload_dataset(client, admin_token, pid, cases, "RX Dataset")

    resp = client.post(
        f"/api/v1/projects/{pid}/evaluations/run",
        json={
            "dataset_version_id": ids["version_id"],
            "scorer_configs": [
                {
                    "scorer_name": "regex",
                    "config": {"pattern": r"\d{4}-\d{2}-\d{2}"},
                }
            ],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["passed_cases"] == 1
    assert data["failed_cases"] == 1


# ---------------------------------------------------------------------------
# Test: Length scorer
# ---------------------------------------------------------------------------


def test_evaluation_run_length_scorer(client: TestClient, admin_token: str) -> None:
    cases = [
        {
            "case_id": "ln-001",
            "prompt": "Write a haiku.",
            "expected_behavior": "5-100 chars",
            "candidate_response": "An old silent pond",
        },
        {
            "case_id": "ln-002",
            "prompt": "Write a haiku.",
            "expected_behavior": "5-100 chars",
            "candidate_response": "X",   # Too short (1 char)
        },
    ]
    pid = _create_project(client, admin_token, "Length Project")
    ids = _upload_dataset(client, admin_token, pid, cases, "LN Dataset")

    resp = client.post(
        f"/api/v1/projects/{pid}/evaluations/run",
        json={
            "dataset_version_id": ids["version_id"],
            "scorer_configs": [
                {
                    "scorer_name": "length",
                    "config": {"unit": "chars", "min_length": 5, "max_length": 100},
                }
            ],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["passed_cases"] == 1
    assert data["failed_cases"] == 1


# ---------------------------------------------------------------------------
# Test: Multiple scorers simultaneously
# ---------------------------------------------------------------------------


def test_evaluation_run_multiple_scorers(client: TestClient, admin_token: str) -> None:
    cases = [
        {
            "case_id": "ms-001",
            "prompt": "Describe AI safety.",
            "expected_behavior": "Mention safety, avoid harmful content, min 10 chars",
            "candidate_response": "AI safety involves ensuring systems behave reliably.",
        },
    ]
    pid = _create_project(client, admin_token, "MultiScorer Project")
    ids = _upload_dataset(client, admin_token, pid, cases, "MS Dataset")

    resp = client.post(
        f"/api/v1/projects/{pid}/evaluations/run",
        json={
            "dataset_version_id": ids["version_id"],
            "scorer_configs": [
                {
                    "scorer_name": "required_keywords",
                    "config": {"keywords": ["safety"]},
                },
                {
                    "scorer_name": "prohibited_keywords",
                    "config": {"keywords": ["harm"]},
                },
                {
                    "scorer_name": "length",
                    "config": {"min_length": 10},
                },
            ],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "completed"
    assert data["passed_cases"] == 1  # All three scorers pass for ms-001


# ---------------------------------------------------------------------------
# Test: Unknown scorer name → 422
# ---------------------------------------------------------------------------


def test_evaluation_run_unknown_scorer_returns_422(
    client: TestClient, admin_token: str
) -> None:
    pid = _create_project(client, admin_token, "Unknown Scorer Project")
    ids = _upload_dataset(client, admin_token, pid, CASES_EXACT, "DS")

    resp = client.post(
        f"/api/v1/projects/{pid}/evaluations/run",
        json={
            "dataset_version_id": ids["version_id"],
            "scorer_configs": [{"scorer_name": "nonexistent_scorer", "config": {}}],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Test: Nonexistent dataset version → 404
# ---------------------------------------------------------------------------


def test_evaluation_run_bad_version_id_returns_404(
    client: TestClient, admin_token: str
) -> None:
    pid = _create_project(client, admin_token, "Bad Version Project")
    resp = client.post(
        f"/api/v1/projects/{pid}/evaluations/run",
        json={
            "dataset_version_id": "00000000-0000-0000-0000-000000000000",
            "scorer_configs": [{"scorer_name": "exact_match", "config": {"expected": "x"}}],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Test: List evaluation runs
# ---------------------------------------------------------------------------


def test_list_evaluation_runs(client: TestClient, admin_token: str) -> None:
    pid = _create_project(client, admin_token, "List Runs Project")
    ids = _upload_dataset(client, admin_token, pid, CASES_EXACT, "LR Dataset")

    for _ in range(2):
        client.post(
            f"/api/v1/projects/{pid}/evaluations/run",
            json={
                "dataset_version_id": ids["version_id"],
                "scorer_configs": [{"scorer_name": "length", "config": {"min_length": 1}}],
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    list_resp = client.get(
        f"/api/v1/projects/{pid}/evaluations",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert list_resp.status_code == 200
    assert len(list_resp.json()) >= 2


# ---------------------------------------------------------------------------
# Test: Get run details by ID
# ---------------------------------------------------------------------------


def test_get_evaluation_run_by_id(client: TestClient, admin_token: str) -> None:
    pid = _create_project(client, admin_token, "Get Run Project")
    ids = _upload_dataset(client, admin_token, pid, CASES_EXACT, "GR Dataset")

    run_resp = client.post(
        f"/api/v1/projects/{pid}/evaluations/run",
        json={
            "dataset_version_id": ids["version_id"],
            "scorer_configs": [{"scorer_name": "length", "config": {"min_length": 1}}],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    run_id = run_resp.json()["id"]

    get_resp = client.get(
        f"/api/v1/projects/{pid}/evaluations/{run_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == run_id
    assert get_resp.json()["status"] == "completed"


# ---------------------------------------------------------------------------
# Test: Filter scores by scorer_name
# ---------------------------------------------------------------------------


def test_get_scores_filtered_by_scorer(client: TestClient, admin_token: str) -> None:
    pid = _create_project(client, admin_token, "Score Filter Project")
    ids = _upload_dataset(client, admin_token, pid, CASES_EXACT, "SF Dataset")

    run_resp = client.post(
        f"/api/v1/projects/{pid}/evaluations/run",
        json={
            "dataset_version_id": ids["version_id"],
            "scorer_configs": [
                {"scorer_name": "length", "config": {"min_length": 1}},
                {"scorer_name": "regex", "config": {"pattern": r"\d"}},
            ],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    run_id = run_resp.json()["id"]

    scores_resp = client.get(
        f"/api/v1/projects/{pid}/evaluations/{run_id}/scores",
        params={"scorer_name": "length"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert scores_resp.status_code == 200
    for s in scores_resp.json():
        assert s["scorer_name"] == "length"


# ---------------------------------------------------------------------------
# Test: Filter scores by passed=True
# ---------------------------------------------------------------------------


def test_get_scores_filtered_by_passed(client: TestClient, admin_token: str) -> None:
    pid = _create_project(client, admin_token, "Pass Filter Project")
    ids = _upload_dataset(client, admin_token, pid, CASES_EXACT, "PF Dataset")

    run_resp = client.post(
        f"/api/v1/projects/{pid}/evaluations/run",
        json={
            "dataset_version_id": ids["version_id"],
            "scorer_configs": [
                {"scorer_name": "exact_match", "config": {"expected": "4"}},
            ],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    run_id = run_resp.json()["id"]

    # Only passing scores
    passed_resp = client.get(
        f"/api/v1/projects/{pid}/evaluations/{run_id}/scores",
        params={"passed": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert passed_resp.status_code == 200
    for s in passed_resp.json():
        assert s["passed"] == 1

    # Only failing scores
    failed_resp = client.get(
        f"/api/v1/projects/{pid}/evaluations/{run_id}/scores",
        params={"passed": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    for s in failed_resp.json():
        assert s["passed"] == 0


# ---------------------------------------------------------------------------
# Test: Unauthenticated request → 401
# ---------------------------------------------------------------------------


def test_trigger_run_requires_auth(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/projects/some-id/evaluations/run",
        json={
            "dataset_version_id": "some-version",
            "scorer_configs": [{"scorer_name": "length", "config": {}}],
        },
    )
    assert resp.status_code == 401
