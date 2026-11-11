from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from app.core.config import settings
from app.core.database import Base, engine
from app.api.v1.api import api_router
import app.models  # Ensure all SQLAlchemy models are registered

# Initialize database schema tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="AI Model Evaluation & Benchmarking Platform API",
    version="0.1.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
)

# Configure CORS middleware
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Include v1 API router
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/", response_class=HTMLResponse, tags=["Root"])
def root_dashboard():
    """Serves a clean platform landing page with direct links to documentation and health."""
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{settings.PROJECT_NAME} - AI Evaluation Platform</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-slate-950 text-slate-100 min-h-screen flex flex-col items-center justify-center p-6 font-sans">
        <div class="max-w-2xl w-full bg-slate-900 border border-slate-800 rounded-xl p-8 shadow-2xl">
            <div class="flex items-center space-x-3 mb-4">
                <div class="w-4 h-4 rounded-full bg-emerald-500 animate-pulse"></div>
                <h1 class="text-3xl font-bold tracking-tight text-white">{settings.PROJECT_NAME}</h1>
                <span class="text-xs bg-cyan-950 text-cyan-400 border border-cyan-800 px-2.5 py-1 rounded-full font-mono">v0.1.0</span>
            </div>
            <p class="text-slate-400 mb-6 leading-relaxed">
                Production-grade AI Model Evaluation & Benchmarking Platform. Ingest evaluation datasets, execute deterministic rule assertions, calibrate multi-rater human rubrics, and generate audit-ready regression reports.
            </p>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-8">
                <a href="{settings.API_V1_STR}/docs" class="p-4 rounded-lg bg-slate-800/80 hover:bg-slate-800 border border-slate-700/60 transition block">
                    <div class="font-semibold text-white mb-1">Interactive API Docs &rarr;</div>
                    <div class="text-xs text-slate-400">Swagger UI contract for evaluation runs, rubrics, and datasets</div>
                </a>
                <a href="{settings.API_V1_STR}/health" class="p-4 rounded-lg bg-slate-800/80 hover:bg-slate-800 border border-slate-700/60 transition block">
                    <div class="font-semibold text-white mb-1">Health & Telemetry &rarr;</div>
                    <div class="text-xs text-slate-400">Real-time database connectivity and service state</div>
                </a>
            </div>
            <div class="text-xs text-slate-500 flex justify-between border-t border-slate-800 pt-4">
                <span>Environment: <strong class="text-slate-400">{settings.ENVIRONMENT}</strong></span>
                <span>API Prefix: <strong class="text-slate-400 font-mono">{settings.API_V1_STR}</strong></span>
            </div>
        </div>
    </body>
    </html>
    """
