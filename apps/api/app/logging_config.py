import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    """Leveled, timestamped logging to stdout — deliberately not a full
    structured-JSON/observability stack (execution IDs, log aggregation)
    yet. That's P1 per the architecture's decision log; this is the
    minimum needed for the unhandled-exception handler in app.errors to
    leave a trace instead of failing silently."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
