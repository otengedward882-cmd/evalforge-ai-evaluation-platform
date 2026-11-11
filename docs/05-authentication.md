# Authentication & Role-Based Access Control (RBAC)

EvalForge implements a stateless JSON Web Token (JWT) authentication architecture using cryptographic signatures and strict Role-Based Access Control (RBAC).

---

## 1. Authentication Lifecycle

```mermaid
sequenceDiagram
    autonumber
    actor Client as Frontend Client
    participant AuthAPI as FastAPI /auth Router
    participant Sec as Security Engine (bcrypt)
    participant DB as PostgreSQL / SQLite
    participant Guard as RBAC Guard (require_roles)

    Note over Client,AuthAPI: Registration & Bootstrap
    Client->>AuthAPI: POST /api/v1/auth/register {email, password, full_name}
    AuthAPI->>DB: Check if first user in database
    alt Is First User
        AuthAPI->>Sec: Hash password via bcrypt (rounds=12)
        AuthAPI->>DB: Persist User with role='admin'
    else Subsequent User
        AuthAPI->>Sec: Hash password via bcrypt (rounds=12)
        AuthAPI->>DB: Persist User with role='evaluator'
    end
    AuthAPI-->>Client: 201 Created {id, email, role}

    Note over Client,AuthAPI: Login & Token Issuance
    Client->>AuthAPI: POST /api/v1/auth/login/json {email, password}
    AuthAPI->>DB: Query User by email
    AuthAPI->>Sec: verify_password(plain, hashed)
    Sec-->>AuthAPI: True
    AuthAPI->>Sec: create_access_token(sub=user.id, role=user.role)
    AuthAPI-->>Client: 200 OK {access_token, token_type="bearer", role}

    Note over Client,Guard: Protected Resource Access
    Client->>Guard: GET /api/v1/auth/admin-only (Header: Bearer <token>)
    Guard->>Sec: decode_access_token(token)
    Guard->>DB: Fetch active user record
    alt User has ADMIN role
        Guard-->>Client: 200 OK {status: "authorized"}
    else User is EVALUATOR / REVIEWER
        Guard-->>Client: 403 Forbidden ("Operation not permitted")
    end
```

---

## 2. Supported User Roles

| Role | Scope | Permitted Actions |
| :--- | :---: | :--- |
| **`ADMIN`** | Platform-Wide | Provision users, manage projects, configure rubrics, trigger automated runs, review & adjudicate, view audit trails. |
| **`EVALUATOR`** | Project-Level | Upload datasets, trigger automated evaluation runs, perform double-blind human rubric reviews, view reports. |
| **`REVIEWER`** | Read & Review | Inspect test cases and scorecards, perform read-only evaluations, export audit reports. |

---

## 3. Cryptographic & Security Safeguards

1. **Password Hashing:** Passwords are truncated to 72 bytes (standard bcrypt boundary) and salted with 12 rounds of bcrypt work factor. Plaintext passwords are never logged, stored, or exposed.
2. **Stateless JWT Claims:** Tokens are signed using HMAC-SHA256 (`HS256`) with standard claims:
   * `sub`: User UUID identifier.
   * `role`: User authorization level.
   * `iat`: Token issuance UTC timestamp.
   * `exp`: Token expiration timestamp (default: 24 hours).
3. **Database Constraints:** User emails are strictly validated via Pydantic `EmailStr` and enforced through unique B-tree indexes on `users.email`.
4. **FastAPI Dependency Guards:** Endpoints enforce access rules via declarative dependencies (`require_admin`, `require_evaluator`, `require_reviewer`).
