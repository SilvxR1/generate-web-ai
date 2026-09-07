from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.errors import register_exception_handlers
from app.logging_config import configure_logging
from app.routers.businesses import business_summaries_router
from app.routers.businesses import router as businesses_router
from app.routers.health import router as health_router
from app.routers.internal_automation import router as internal_automation_router


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(title=settings.service_name, version=settings.version)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(businesses_router)
    app.include_router(business_summaries_router)
    app.include_router(internal_automation_router)

    return app


app = create_app()
