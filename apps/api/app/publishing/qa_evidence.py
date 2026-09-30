"""Visual QA evidence bound to an immutable artifact (H1.2).

Visual QA findings are stored on the draft's GenerativeWebsiteArtifact row
(`visual_qa_state`), never inside the artifact — its bytes (and its
SHA-256) are exactly what preview and publish deploy. Each evidence record
names the artifact identity and the `_headers` policy it was produced
under, so it is traceable to what it describes and can never be silently
reused for different content: `evidence_is_current` is False as soon as
the draft's artifact identity differs (or evidence predates H1.2 and names
none). Existing keys (`passed`, `findings`) are unchanged for readers.
"""

from datetime import UTC, datetime
from typing import Any

QA_EVIDENCE_VERSION = 1


def visual_qa_evidence(
    *,
    passed: bool,
    findings: list[dict[str, Any]],
    artifact_sha256: str | None,
    headers_sha256: str | None,
    source: str,
) -> dict[str, Any]:
    return {
        "passed": bool(passed),
        "findings": findings,
        "evidence_version": QA_EVIDENCE_VERSION,
        # The identity of the exact bytes the browser checked (None only for
        # legacy drafts QA'd from a rebuild — such evidence is never current).
        "artifact_sha256": artifact_sha256,
        "headers_sha256": headers_sha256,
        "source": source,  # "execution-host" | "api-visual-qa" | ...
        "produced_at": datetime.now(UTC).isoformat(),
    }


def evidence_is_current(state: dict[str, Any] | None, artifact_sha256: str | None) -> bool:
    """True only when the evidence describes THIS artifact identity."""
    if not state or artifact_sha256 is None:
        return False
    return state.get("evidence_version") == QA_EVIDENCE_VERSION and state.get("artifact_sha256") == artifact_sha256
