"""Request shape for POST /businesses/analyze (app.routers.businesses).
The response reuses app.analysis.analyzer.BusinessAnalysisResult
directly as its schema — the same convention this codebase already
follows for BusinessConfig (see BusinessWriteRequest.config in
app.schemas.business): a domain Pydantic model used as an API schema
directly, rather than duplicated field-for-field.
"""

from pydantic import BaseModel, ConfigDict, Field


class BusinessAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Same bound as BusinessBase.raw_description (app.schemas.business):
    # a runaway paste must not reach the LLM unbounded.
    briefing: str = Field(min_length=10, max_length=8000)
