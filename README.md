# EvalForge — AI Model Evaluation & Benchmarking Platform

[![CI Pipeline](https://github.com/otengedward882-cmd/evalforge-ai-evaluation-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/otengedward882-cmd/evalforge-ai-evaluation-platform/actions)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://www.postgresql.org)
[![React](https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.2-3178C6?style=flat-square&logo=typescript&logoColor=white)](https://www.typescriptlang.org)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white)](https://www.docker.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)

EvalForge is a production-oriented AI evaluation and benchmarking platform engineered to test, score, validate, and compare Large Language Model (LLM) responses. It bridges automated deterministic assertions (regex, JSON schema enforcement, canary token checks) with calibrated human-in-the-loop scoring (Likert scales, double-blind reviews, and multi-rater adjudication).

---

## 📌 Problem Statement

Evaluating generative AI models in software workflows presents acute operational challenges:
1. **Non-Deterministic Degradation:** Model updates, quantization, or system prompt modifications can inadvertently cause regressions in instruction adherence and safety boundaries.
2. **Disconnected Evaluation Silos:** Automated programmatic tests and qualitative human review rubrics frequently live in incompatible systems without unified audit trails.
3. **Auditability & Provenance:** Teams lack immutable dataset versioning linked directly to quantitative pass rates, inter-annotator agreement metrics, and failure categorization.

EvalForge provides a unified, containerized platform enabling AI engineers, evaluators, and QA leads to ingest datasets, execute rule suites, resolve reviewer scoring discrepancies, and generate audit-ready regression reports.

---

## 👥 Target Users

* **AI Evaluation Specialists & Annotators:** Review candidate model outputs, score adherence against detailed rubrics, and document failure evidence.
* **LLM & Systems Engineers:** Automate CI/CD regression suites verifying schema contracts, token lengths, and canary token retention before model deployments.
* **Technical Quality Leads & Auditors:** Review multi-evaluator score variance, adjudicate disputed cases, and export audit trails.

---

## 🏗️ System Architecture

```mermaid
flowchart TD
    subgraph Client ["Frontend Layer (Vite + React + TS)"]
        UI["Review Workspace & Dashboard"]
        QueryCache["TanStack Query Cache"]
    end

    subgraph API ["Application Layer (FastAPI)"]
        AuthMid["JWT Auth & RBAC Middleware"]
        Router["REST Routers (/api/v1)"]
        
        subgraph Engine ["Evaluation Engine"]
            Deterministic["Rule-Based Scorers<br/>(Regex, Schema, Keywords, Length)"]
            Adjudicator["Multi-Rater Discrepancy Analyzer"]
            Metrics["Aggregator & Regression Service"]
        end
    end

    subgraph Data ["Persistence Layer (PostgreSQL 16 / SQLite)"]
        Relational["Relational Schema<br/>(Projects, Versions, Cases, Rubrics)"]
        Metadata["JSONB Metadata & Rules"]
    end

    UI -->|REST / JSON| AuthMid
    AuthMid --> Router
    Router --> Engine
    Engine --> Relational
```

---

## ⚡ Main Features

* **Multi-Format Dataset Ingestion:** Stream-parse CSV and JSONL datasets with schema validation, malformed record detection, and immutable versioning.
* **Deterministic Evaluation Engine:** Automated rules verifying exact matches, required keywords, forbidden canary tokens, regex patterns, and JSON schema conformity.
* **Configurable Rubric Builder:** Declarative rubrics supporting binary, Likert (1-5), and continuous scales with criterion guidelines and anchor examples.
* **Double-Blind Human Review Queue:** Side-by-side evaluation workspace displaying prompts, candidate outputs, reference answers, and criteria.
* **Reviewer Discrepancy Adjudication:** Flags cases where independent evaluators diverge beyond variance thresholds for lead resolution.
* **Audit-Ready Export & Benchmarks:** Comprehensive score matrices exportable to CSV and structured JSON.

---

## 🛠️ Technology Stack

* **Backend:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic, Uvicorn
* **Database:** PostgreSQL 16 (production), SQLite (in-memory/local development fallback)
* **Frontend:** React 18, TypeScript, Vite, Tailwind CSS, TanStack Query, Lucide Icons
* **DevOps & Testing:** Docker, Docker Compose, pytest, pytest-asyncio, Ruff, GitHub Actions

---

## 🚀 Quickstart & Installation

### Option 1: Local Development Setup

#### Prerequisites
* Python 3.11+
* Git

```bash
# 1. Clone the repository
git clone https://github.com/otengedward882-cmd/evalforge-ai-evaluation-platform.git
cd evalforge-ai-evaluation-platform

# 2. Set up virtual environment
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

# 3. Install backend dependencies
pip install -r backend/requirements.txt

# 4. Copy environment configuration
cp .env.example .env

# 5. Run the FastAPI development server
cd backend
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Once started:
* **Interactive Dashboard & API Documentation:** [http://localhost:8000/api/v1/docs](http://localhost:8000/api/v1/docs)
* **Health & Telemetry Endpoint:** [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)

---

### Option 2: Docker Compose Setup

```bash
# Build and start all services (PostgreSQL, Backend API, Frontend SPA)
docker compose up --build -d

# Check service logs
docker compose logs -f backend
```

---

## 🧪 Testing & Quality Assurance

Run the automated test suite with pytest:

```bash
# Execute unit and integration tests
python -m pytest tests -v

# Run with coverage report
python -m pytest tests --cov=backend/app --cov-report=term-missing
```

---

## 🔒 Security Architecture

* **Input Sanitization:** All payload structures validated via Pydantic schemas; zero raw string SQL interpolation.
* **Authentication:** Stateless JWT bearer tokens signed via HS256 with expiration and role verification.
* **Credential Isolation:** Strict separation of environment configurations; no secret keys committed to version control.

---

## 📄 License

This project is open-source and licensed under the [MIT License](LICENSE).
