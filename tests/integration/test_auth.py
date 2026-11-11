import pytest


def test_register_first_user_becomes_admin(client):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "firstuser@evalforge.dev",
            "password": "SuperSecretPassword123!",
            "full_name": "First User",
            "role": "evaluator"
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "firstuser@evalforge.dev"
    assert data["role"] == "admin"
    assert "id" in data


def test_register_subsequent_user_retains_evaluator_role(client, test_admin):
    # test_admin exists, so user_count >= 1
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "newevaluator@evalforge.dev",
            "password": "EvaluatorPassword123!",
            "full_name": "Alex Evaluator",
            "role": "evaluator"
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "newevaluator@evalforge.dev"
    assert data["role"] == "evaluator"


def test_register_duplicate_email_conflict(client, test_admin):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": test_admin.email,
            "password": "AnotherPassword123!",
            "full_name": "Duplicate User"
        }
    )
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def test_login_json_success(client, test_admin):
    response = client.post(
        "/api/v1/auth/login/json",
        json={
            "email": test_admin.email,
            "password": "SuperSecretPassword123!"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["role"] == "admin"
    assert data["user_id"] == test_admin.id


def test_login_form_oauth2_success(client, test_admin):
    response = client.post(
        "/api/v1/auth/login",
        data={
            "username": test_admin.email,
            "password": "SuperSecretPassword123!"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_invalid_credentials(client, test_admin):
    response = client.post(
        "/api/v1/auth/login/json",
        json={
            "email": test_admin.email,
            "password": "IncorrectPassword!"
        }
    )
    assert response.status_code == 401
    assert "Incorrect email or password" in response.json()["detail"]


def test_get_current_user_profile(client, test_evaluator, evaluator_token):
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {evaluator_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == test_evaluator.email
    assert data["full_name"] == test_evaluator.full_name
    assert data["role"] == "evaluator"


def test_get_current_user_unauthorized(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_rbac_admin_route_permitted_for_admin(client, admin_token):
    response = client.get(
        "/api/v1/auth/admin-only",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "authorized"


def test_rbac_admin_route_forbidden_for_evaluator(client, evaluator_token):
    response = client.get(
        "/api/v1/auth/admin-only",
        headers={"Authorization": f"Bearer {evaluator_token}"}
    )
    assert response.status_code == 403
    assert "Operation not permitted" in response.json()["detail"]
