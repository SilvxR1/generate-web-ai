"""v0.2 R4.1 — what the isolated execution host does with one job.

    generated source -> sandboxed build -> sandboxed Visual QA -> candidate

Runs on the execution host (never needs the API's settings, database or
any credential). The source was produced trusted-side (BusinessTruth ->
provider -> manifest); here it is only materialized through the same
path/extension validation as ever (workspace.write_manifest), with the
engine re-authoring every piece of scaffolding, then built and browsed
exclusively inside the untrusted build zone. The result is a candidate,
nothing more: the control plane decides everything that follows.
"""

import logging
import time
from pathlib import Path

from app.creative.frontend_engine.browser_qa import BrowserQAUnavailableError
from app.creative.frontend_engine.build import GenerativeBuildError, build_generative_workspace
from app.creative.frontend_engine.manifest import GeneratedFile, GeneratedProjectManifest
from app.creative.frontend_engine.sandbox import SandboxError, SandboxRunner, detect_runner
from app.creative.frontend_engine.sandboxed_browser_qa import MAX_OFFLINE_ASSET_BYTES, run_browser_qa_sandboxed
from app.creative.frontend_engine.templates import ASTRO_CONFIG, TSCONFIG, build_package_json
from app.creative.frontend_engine.workspace import (
    WorkspaceSecurityError,
    allocate_workspace,
    cleanup_workspace,
    write_manifest,
)
from app.domain.enums import GenerationFailureKind
from app.worker.protocol import (
    MAX_SOURCE_ARCHIVE_BYTES,
    ExecutionRequest,
    ExecutionResult,
    ProtocolError,
    VisualQAReport,
    b64,
    pack_files,
    sha256_hex,
    unb64,
    unpack_source,
)

logger = logging.getLogger(__name__)


def _failed(request: ExecutionRequest, kind: GenerationFailureKind, error: str, **metadata: object) -> ExecutionResult:
    return ExecutionResult(
        job_id=request.job_id,
        attempt=request.attempt,
        status="failed",
        failure_kind=kind,
        error=error[:2000],
        metadata=dict(metadata),
    )


def _build_failure_kind(message: str) -> GenerationFailureKind:
    if "drift" in message or "lockfile" in message:
        return GenerationFailureKind.DEPENDENCY_DRIFT
    if "timed out" in message or "exit -" in message:
        return GenerationFailureKind.RESOURCE_LIMIT
    if "refusing to run untrusted" in message:
        return GenerationFailureKind.SANDBOX_UNAVAILABLE
    return GenerationFailureKind.BUILD


def execute(
    request: ExecutionRequest, *, runner: SandboxRunner | None = None, prepared_dependencies: Path | None = None
) -> ExecutionResult:
    try:
        runner = runner or detect_runner()
    except SandboxError as exc:
        return _failed(request, GenerationFailureKind.SANDBOX_UNAVAILABLE, str(exc))
    metadata: dict[str, object] = {"runner": runner.name, "limits_enforced": runner.limits_enforced()}

    try:
        archive = unb64(request.source_archive, limit=MAX_SOURCE_ARCHIVE_BYTES)
        if sha256_hex(archive) != request.source_sha256:
            raise ProtocolError("source archive does not match its SHA-256")
        source = unpack_source(archive)
        manifest = GeneratedProjectManifest(
            files=[GeneratedFile(path=path, content=data.decode("utf-8")) for path, data in source.items()]
        )
        assets = {url: unb64(data, limit=MAX_OFFLINE_ASSET_BYTES) for url, data in request.offline_assets.items()}
    except (ProtocolError, UnicodeDecodeError, ValueError) as exc:
        return _failed(request, GenerationFailureKind.CANDIDATE_REJECTED, f"invalid execution request: {exc}")

    workspace = allocate_workspace()
    try:
        try:
            write_manifest(
                workspace,
                manifest,
                package_json=build_package_json(name="gwa-generated-site", additional_dependencies=[]),
                astro_config=ASTRO_CONFIG,
                tsconfig=TSCONFIG,
            )
        except WorkspaceSecurityError as exc:
            return _failed(request, GenerationFailureKind.CANDIDATE_REJECTED, str(exc), **metadata)

        started = time.monotonic()
        try:
            artifact = build_generative_workspace(
                workspace,
                business_id=str(request.business_id),
                api_base_url=request.api_base_url,
                runner=runner,
                prepared_dependencies=prepared_dependencies,
            )
        except GenerativeBuildError as exc:
            return _failed(request, _build_failure_kind(str(exc)), str(exc), **metadata)
        metadata["build_ms"] = int((time.monotonic() - started) * 1000)
    finally:
        cleanup_workspace(workspace)

    report: VisualQAReport | None = None
    if request.run_visual_qa:
        started = time.monotonic()
        try:
            qa = run_browser_qa_sandboxed(
                artifact.files, offline_assets=assets, capture_screenshots=True, runner=runner
            )
        except BrowserQAUnavailableError as exc:
            return _failed(request, GenerationFailureKind.SANDBOX_UNAVAILABLE, str(exc), **metadata)
        metadata["visual_qa_ms"] = int((time.monotonic() - started) * 1000)
        report = VisualQAReport(
            passed=qa.passed,
            findings=[
                {"viewport": f.viewport, "check": f.check, "passed": f.passed, "detail": f.detail} for f in qa.findings
            ],
            blocked_requests=qa.blocked_requests,
            screenshots={name: b64(png) for name, png in qa.screenshots.items()},
        )

    candidate = pack_files(artifact.files)
    logger.info(
        "generation job executed job_id=%s files=%d bytes=%d", request.job_id, len(artifact.files), len(candidate)
    )
    return ExecutionResult(
        job_id=request.job_id,
        attempt=request.attempt,
        status="succeeded",
        candidate_archive=b64(candidate),
        candidate_sha256=sha256_hex(candidate),
        visual_qa=report,
        metadata=metadata,
    )
