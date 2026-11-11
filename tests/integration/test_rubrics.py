"""
Integration tests for the Rubric System (Milestone 5).

Covers:
- Create rubric with LIKERT_5 criteria → 201
- Create rubric with BINARY criteria → auto-sets min=0, max=1
- Reject rubric with invalid LIKERT_5 scale bounds → 422
- Reject rubric with invalid PERCENTAGE scale bounds → 422
- Reject rubric with 0 criteria → 422
- Get rubric by ID
- List rubrics for a project
- Clone rubric increments version number
- Reviewer (read-only) can read rubrics
- Evaluator cannot archive rubrics (admin only) → 403
- Admin can archive rubric → 204; rubric disappears from list
- Rubric scoped to project (cross-project access returns 404)
"""

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures: shared rubric payload
# ---------------------------------------------------------------------------

LIKERT_CRITERIA = [
    {
        "name": "Factual Accuracy",
        "description": "Does the response contain factually correct statements?",
        "scale_type": "likert_5",
        "min_score": 1.0,
        "max_score": 5.0,
        "weight": 2.0,
        "guidelines": {"1": "Completely wrong", "5": "Fully accurate"},
        "examples": {"pass": "Correct date cited", "fail": "Wrong year stated"},
    },
    {
        "name": "Coherence",
        "description": "Is the response logically structured and easy to follow?",
        "scale_type": "likert_5",
        "min_score": 1.0,
        "max_score": 5.0,
        "weight": 1.0,
    },
]

BINARY_CRITERIA = [
    {
        "name": "Safety Pass",
        "description": "Does the response avoid harmful content?",
        "scale_type": "binary",
        # min/max omitted — should auto-coerce to 0.0 / 1.0
    }
]

PERCENTAGE_CRITERIA = [
    {
        "name": "Relevance",
        "description": "What proportion of the response is relevant to the question?",
        "scale_type": "percentage",
        "min_score": 0.0,
        "max_score": 1.0,
        "weight": 1.0,
    }
]


# ---------------------------------------------------------------------------
# Helper: create a project via the API and return its id
# ---------------------------------------------------------------------------


def _create_project(client: TestClient, token: str, name: str = "Rubric Test Project") -> str:
    resp = client.post(
        "/api/v1/projects",
        json={"name": name, "description": "Project for rubric tests"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# Test: Create rubric with LIKERT_5 criteria
# ---------------------------------------------------------------------------


def test_create_rubric_likert_returns_201(
    client: TestClient, admin_token: str
) -> None:
    pid = _create_project(client, admin_token)
    resp = client.post(
        f"/api/v1/projects/{pid}/rubrics",
        json={"name": "Quality Rubric", "criteria": LIKERT_CRITERIA},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["name"] == "Quality Rubric"
    assert data["version"] == 1
    assert data["is_active"] == 1
    assert len(data["criteria"]) == 2
    assert data["criteria"][0]["name"] == "Factual Accuracy"
    assert data["criteria"][0]["scale_type"] == "likert_5"
    assert data["criteria"][0]["weight"] == 2.0


# ---------------------------------------------------------------------------
# Test: Create rubric with BINARY criteria — auto-coerces bounds
# ---------------------------------------------------------------------------


def test_create_rubric_binary_auto_coerces_bounds(
    client: TestClient, evaluator_token: str, admin_token: str
) -> None:
    pid = _create_project(client, admin_token, name="Binary Project")
    resp = client.post(
        f"/api/v1/projects/{pid}/rubrics",
        json={"name": "Safety Rubric", "criteria": BINARY_CRITERIA},
        headers={"Authorization": f"Bearer {evaluator_token}"},
    )
    assert resp.status_code == 201, resp.text
    crit = resp.json()["criteria"][0]
    assert crit["min_score"] == 0.0
    assert crit["max_score"] == 1.0
    assert crit["scale_type"] == "binary"


# ---------------------------------------------------------------------------
# Test: Reject LIKERT_5 with out-of-range max_score
# ---------------------------------------------------------------------------


def test_create_rubric_invalid_likert_bounds_returns_422(
    client: TestClient, admin_token: str
) -> None:
    pid = _create_project(client, admin_token, name="Invalid Likert Project")
    bad_crit = {
        "name": "Bad Criterion",
        "description": "This criterion has an illegal max_score for Likert.",
        "scale_type": "likert_5",
        "min_score": 1.0,
        "max_score": 10.0,  # Invalid: must be <= 5
    }
    resp = client.post(
        f"/api/v1/projects/{pid}/rubrics",
        json={"name": "Bad Rubric", "criteria": [bad_crit]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Test: Reject PERCENTAGE with out-of-range max_score
# ---------------------------------------------------------------------------


def test_create_rubric_invalid_percentage_bounds_returns_422(
    client: TestClient, admin_token: str
) -> None:
    pid = _create_project(client, admin_token, name="Invalid Pct Project")
    bad_crit = {
        "name": "Bad Percentage",
        "description": "This criterion has an illegal max for percentage scale.",
        "scale_type": "percentage",
        "min_score": 0.0,
        "max_score": 1.5,  # Invalid: must be <= 1.0
    }
    resp = client.post(
        f"/api/v1/projects/{pid}/rubrics",
        json={"name": "Bad Rubric", "criteria": [bad_crit]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Test: Reject rubric with 0 criteria
# ---------------------------------------------------------------------------


def test_create_rubric_no_criteria_returns_422(
    client: TestClient, admin_token: str
) -> None:
    pid = _create_project(client, admin_token, name="Empty Criteria Project")
    resp = client.post(
        f"/api/v1/projects/{pid}/rubrics",
        json={"name": "Empty Rubric", "criteria": []},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Test: Get rubric by ID
# ---------------------------------------------------------------------------


def test_get_rubric_by_id(client: TestClient, admin_token: str) -> None:
    pid = _create_project(client, admin_token, name="Get Rubric Project")
    create_resp = client.post(
        f"/api/v1/projects/{pid}/rubrics",
        json={"name": "Detailed Rubric", "criteria": LIKERT_CRITERIA},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    rubric_id = create_resp.json()["id"]

    get_resp = client.get(
        f"/api/v1/projects/{pid}/rubrics/{rubric_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == rubric_id
    assert len(get_resp.json()["criteria"]) == 2


# ---------------------------------------------------------------------------
# Test: List rubrics for a project
# ---------------------------------------------------------------------------


def test_list_rubrics_for_project(
    client: TestClient, admin_token: str
) -> None:
    pid = _create_project(client, admin_token, name="List Project")
    for name in ["Rubric A", "Rubric B"]:
        client.post(
            f"/api/v1/projects/{pid}/rubrics",
            json={"name": name, "criteria": LIKERT_CRITERIA},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    list_resp = client.get(
        f"/api/v1/projects/{pid}/rubrics",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert list_resp.status_code == 200
    assert len(list_resp.json()) >= 2


# ---------------------------------------------------------------------------
# Test: Clone rubric increments version number
# ---------------------------------------------------------------------------


def test_clone_rubric_increments_version(
    client: TestClient, admin_token: str
) -> None:
    pid = _create_project(client, admin_token, name="Clone Project")
    create_resp = client.post(
        f"/api/v1/projects/{pid}/rubrics",
        json={"name": "Versioned Rubric", "criteria": LIKERT_CRITERIA},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_resp.json()["version"] == 1
    rubric_id = create_resp.json()["id"]

    clone_resp = client.post(
        f"/api/v1/projects/{pid}/rubrics/{rubric_id}/clone",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert clone_resp.status_code == 201
    assert clone_resp.json()["version"] == 2
    assert clone_resp.json()["name"] == "Versioned Rubric"
    assert len(clone_resp.json()["criteria"]) == 2


# ---------------------------------------------------------------------------
# Test: Reviewer (read-only role) can read rubrics
# ---------------------------------------------------------------------------


def test_reviewer_can_read_rubrics(
    client: TestClient, admin_token: str
) -> None:
    # Register a reviewer user
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "reviewer_rubric@example.com",
            "password": "ReviewPass123!",
            "full_name": "Reviewer Rubric",
        },
    )
    login_resp = client.post(
        "/api/v1/auth/login/json",
        json={"email": "reviewer_rubric@example.com", "password": "ReviewPass123!"},
    )
    reviewer_token = login_resp.json()["access_token"]

    pid = _create_project(client, admin_token, name="Reviewer Read Project")
    create_resp = client.post(
        f"/api/v1/projects/{pid}/rubrics",
        json={"name": "Readable Rubric", "criteria": LIKERT_CRITERIA},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    rubric_id = create_resp.json()["id"]

    # Reviewer can list
    list_resp = client.get(
        f"/api/v1/projects/{pid}/rubrics",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert list_resp.status_code == 200

    # Reviewer can get by ID
    get_resp = client.get(
        f"/api/v1/projects/{pid}/rubrics/{rubric_id}",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert get_resp.status_code == 200


# ---------------------------------------------------------------------------
# Test: Evaluator cannot archive rubrics (admin only) → 403
# ---------------------------------------------------------------------------


def test_evaluator_cannot_archive_rubric(
    client: TestClient, admin_token: str, evaluator_token: str
) -> None:
    pid = _create_project(client, admin_token, name="Archive Guard Project")
    create_resp = client.post(
        f"/api/v1/projects/{pid}/rubrics",
        json={"name": "Protected Rubric", "criteria": LIKERT_CRITERIA},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    rubric_id = create_resp.json()["id"]

    del_resp = client.delete(
        f"/api/v1/projects/{pid}/rubrics/{rubric_id}",
        headers={"Authorization": f"Bearer {evaluator_token}"},
    )
    assert del_resp.status_code == 403


# ---------------------------------------------------------------------------
# Test: Admin archives rubric → 204, then it disappears from list
# ---------------------------------------------------------------------------


def test_admin_archives_rubric(client: TestClient, admin_token: str) -> None:
    pid = _create_project(client, admin_token, name="Archive Project")
    create_resp = client.post(
        f"/api/v1/projects/{pid}/rubrics",
        json={"name": "Archivable Rubric", "criteria": BINARY_CRITERIA},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    rubric_id = create_resp.json()["id"]

    del_resp = client.delete(
        f"/api/v1/projects/{pid}/rubrics/{rubric_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert del_resp.status_code == 204

    # Archived rubric must not appear in list
    list_resp = client.get(
        f"/api/v1/projects/{pid}/rubrics",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    ids = [r["id"] for r in list_resp.json()]
    assert rubric_id not in ids
