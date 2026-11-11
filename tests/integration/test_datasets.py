import io
import pytest


@pytest.fixture
def test_project(client, evaluator_token):
    res = client.post(
        "/api/v1/projects",
        json={
            "name": "Customer Support LLM Evaluation",
            "description": "Benchmarking customer support bot response safety and accuracy"
        },
        headers={"Authorization": f"Bearer {evaluator_token}"}
    )
    assert res.status_code == 201
    return res.json()


@pytest.fixture
def test_dataset(client, test_project, evaluator_token):
    res = client.post(
        f"/api/v1/projects/{test_project['id']}/datasets",
        json={
            "name": "Support Golden Testset",
            "description": "500 standard customer queries with golden responses"
        },
        headers={"Authorization": f"Bearer {evaluator_token}"}
    )
    assert res.status_code == 201
    return res.json()


def test_create_and_list_projects(client, evaluator_token):
    res = client.get(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {evaluator_token}"}
    )
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_upload_valid_jsonl_dataset(client, test_project, test_dataset, evaluator_token):
    jsonl_content = (
        '{"case_id": "CS-001", "prompt": "How do I reset my password?", "expected_behavior": "Explain password reset link.", "category": "Auth", "difficulty": "Low"}\n'
        '{"case_id": "CS-002", "prompt": "Can I get a refund after 30 days?", "expected_behavior": "Reference refund policy.", "category": "Billing", "difficulty": "Medium"}\n'
    )
    file_bytes = io.BytesIO(jsonl_content.encode("utf-8"))

    res = client.post(
        f"/api/v1/projects/{test_project['id']}/datasets/{test_dataset['id']}/upload",
        files={"file": ("cases.jsonl", file_bytes, "application/jsonl")},
        headers={"Authorization": f"Bearer {evaluator_token}"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["total_imported"] == 2
    assert data["version_number"] == 1
    assert len(data["checksum_sha256"]) == 64

    # Fetch imported cases
    versions_cases_res = client.get(
        f"/api/v1/projects/{test_project['id']}/datasets/{test_dataset['id']}/versions/cases",
        # Actually our endpoint is /versions/{version_id}/cases, let's test that below
    )


def test_versioning_and_case_filtering(client, test_project, test_dataset, evaluator_token):
    # Upload version 1
    content_v1 = (
        '{"case_id": "V1-01", "prompt": "Prompt 1", "expected_behavior": "Behavior 1", "category": "Safety"}\n'
    )
    res_v1 = client.post(
        f"/api/v1/projects/{test_project['id']}/datasets/{test_dataset['id']}/upload",
        files={"file": ("v1.jsonl", io.BytesIO(content_v1.encode("utf-8")), "application/jsonl")},
        headers={"Authorization": f"Bearer {evaluator_token}"}
    )
    assert res_v1.status_code == 200
    assert res_v1.json()["version_number"] == 1

    # Upload version 2
    content_v2 = (
        '{"case_id": "V2-01", "prompt": "Prompt 2A", "expected_behavior": "Behavior 2A", "category": "Safety"}\n'
        '{"case_id": "V2-02", "prompt": "Prompt 2B", "expected_behavior": "Behavior 2B", "category": "Accuracy"}\n'
    )
    res_v2 = client.post(
        f"/api/v1/projects/{test_project['id']}/datasets/{test_dataset['id']}/upload",
        files={"file": ("v2.jsonl", io.BytesIO(content_v2.encode("utf-8")), "application/jsonl")},
        headers={"Authorization": f"Bearer {evaluator_token}"}
    )
    assert res_v2.status_code == 200
    assert res_v2.json()["version_number"] == 2

    # Query dataset to get latest version ID
    datasets_res = client.get(
        f"/api/v1/projects/{test_project['id']}/datasets",
        headers={"Authorization": f"Bearer {evaluator_token}"}
    )
    dataset_info = datasets_res.json()[0]
    version_id = dataset_info["latest_version"]["id"]

    # Retrieve cases filtered by category
    cases_res = client.get(
        f"/api/v1/projects/{test_project['id']}/datasets/{test_dataset['id']}/versions/{version_id}/cases?category=Safety",
        headers={"Authorization": f"Bearer {evaluator_token}"}
    )
    assert cases_res.status_code == 200
    cases = cases_res.json()
    assert len(cases) == 1
    assert cases[0]["case_id"] == "V2-01"


def test_upload_valid_csv_dataset(client, test_project, test_dataset, evaluator_token):
    csv_content = (
        "case_id,prompt,expected_behavior,category,difficulty\n"
        "CSV-01,What is Python?,Explain high-level programming language.,General,Low\n"
        "CSV-02,Explain recursion.,Define base case and recursive step.,Computer Science,Medium\n"
    )
    res = client.post(
        f"/api/v1/projects/{test_project['id']}/datasets/{test_dataset['id']}/upload",
        files={"file": ("data.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")},
        headers={"Authorization": f"Bearer {evaluator_token}"}
    )
    assert res.status_code == 200
    assert res.json()["total_imported"] == 2


def test_upload_malformed_json_returns_422(client, test_project, test_dataset, evaluator_token):
    bad_jsonl = (
        '{"case_id": "OK-1", "prompt": "Valid line", "expected_behavior": "Good"}\n'
        '{"case_id": "BAD-2", "prompt": "Unclosed quote, "expected_behavior": "Broken"}\n'
    )
    res = client.post(
        f"/api/v1/projects/{test_project['id']}/datasets/{test_dataset['id']}/upload",
        files={"file": ("bad.jsonl", io.BytesIO(bad_jsonl.encode("utf-8")), "application/jsonl")},
        headers={"Authorization": f"Bearer {evaluator_token}"}
    )
    assert res.status_code == 422
    data = res.json()
    assert "detail" in data
    assert any("Malformed JSON syntax" in err["error"] for err in data["detail"]["errors"])


def test_upload_duplicate_case_id_returns_422(client, test_project, test_dataset, evaluator_token):
    duplicate_jsonl = (
        '{"case_id": "DUP-01", "prompt": "Query 1", "expected_behavior": "Ans 1"}\n'
        '{"case_id": "DUP-01", "prompt": "Query 2", "expected_behavior": "Ans 2"}\n'
    )
    res = client.post(
        f"/api/v1/projects/{test_project['id']}/datasets/{test_dataset['id']}/upload",
        files={"file": ("dup.jsonl", io.BytesIO(duplicate_jsonl.encode("utf-8")), "application/jsonl")},
        headers={"Authorization": f"Bearer {evaluator_token}"}
    )
    assert res.status_code == 422
    data = res.json()
    assert any("Duplicate case_id 'DUP-01'" in err["error"] for err in data["detail"]["errors"])


def test_upload_missing_required_fields_returns_422(client, test_project, test_dataset, evaluator_token):
    missing_fields_jsonl = (
        '{"case_id": "MISSING-01", "category": "Safety"}\n'  # Missing prompt and expected_behavior
    )
    res = client.post(
        f"/api/v1/projects/{test_project['id']}/datasets/{test_dataset['id']}/upload",
        files={"file": ("missing.jsonl", io.BytesIO(missing_fields_jsonl.encode("utf-8")), "application/jsonl")},
        headers={"Authorization": f"Bearer {evaluator_token}"}
    )
    assert res.status_code == 422
    data = res.json()
    assert any("Missing required field(s)" in err["error"] for err in data["detail"]["errors"])


def test_upload_unsupported_file_extension(client, test_project, test_dataset, evaluator_token):
    res = client.post(
        f"/api/v1/projects/{test_project['id']}/datasets/{test_dataset['id']}/upload",
        files={"file": ("document.docx", io.BytesIO(b"binary data"), "application/octet-stream")},
        headers={"Authorization": f"Bearer {evaluator_token}"}
    )
    assert res.status_code == 400
    assert "Unsupported file format" in res.json()["detail"]
