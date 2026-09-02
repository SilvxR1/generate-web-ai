import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config import settings
from app.dependencies import get_engine

router = APIRouter()

# Process-start marker for uptime — module import time is close enough
# for a dev/MVP health check, not worth a dedicated startup hook yet.
_started_at = time.monotonic()


@router.get("/health")
def health(engine: Engine = Depends(get_engine)) -> JSONResponse:
    database_status = "ok"
    database_detail: str | None = None
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        database_status = "error"
        database_detail = str(exc)

    overall = "ok" if database_status == "ok" else "degraded"

    payload: dict[str, Any] = {
        "status": overall,
        "service": settings.service_name,
        "version": settings.version,
        "environment": settings.environment,
        "timestamp": datetime.now(UTC).isoformat(),
        "uptime_seconds": round(time.monotonic() - _started_at, 3),
        "dependencies": {
            "database": {"status": database_status, **({"detail": database_detail} if database_detail else {})}
        },
    }

    # A degraded dependency fails the check for anything polling this
    # endpoint (docker-compose healthcheck, a future load balancer) —
    # returning 200 with a "degraded" string buried in the body would
    # look like success to anything that only checks the status code.
    return JSONResponse(status_code=200 if overall == "ok" else 503, content=payload)
