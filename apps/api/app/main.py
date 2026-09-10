from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.errors import register_exception_handlers
from app.logging_config import configure_logging
from app.routers.analytics import router as analytics_router
from app.routers.businesses import business_summaries_router
from app.routers.businesses import router as businesses_router
from app.routers.creative import router as creative_router
from app.routers.health import router as health_router
from app.routers.internal_automation import router as internal_automation_router
from app.routers.public import router as public_router
from app.routers.website_health import router as website_health_router
from app.security import SecurityHeadersMiddleware


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(title=settings.service_name, version=settings.version)

    # Applied to every response, including error responses (Starlette
    # middleware wraps exception handling) — see
    # app.security.headers.SecurityHeadersMiddleware's own docstring for
    # what's set and why HSTS is environment-gated.
    app.add_middleware(SecurityHeadersMiddleware, is_production=settings.environment == "production")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(analytics_router)
    app.include_router(businesses_router)
    app.include_router(business_summaries_router)
    app.include_router(creative_router)
    app.include_router(internal_automation_router)
    app.include_router(public_router)
    app.include_router(website_health_router)

    # Serves whatever LocalStorageProvider (app.storage.local) has saved
    # under settings.local_storage_dir — the dev-only asset storage
    # backend (Phase 3). Directory is created up front so this mount
    # never fails at startup just because nothing's been uploaded yet.
    upload_dir = Path(settings.local_storage_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")

    return app


app = create_app()
