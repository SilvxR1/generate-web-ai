"""R5 — what the execution host does with a SOURCE-ADAPTATION job.

    snapshot (downloaded with the job token, SHA-256 verified)
      -> immutable original (read-only) -> working copy
      -> apply the EXACT stored AdaptationPlan (drift = stop)
      -> trusted `bun install --ignore-scripts` (no lifecycle hooks)
      -> the plan's BuildSpec steps in the runner (bubblewrap, or the
         supervised-process tier for owner-reviewed sources)
      -> static artifact (platform runtime, robots/sitemap, family CSP)
      -> Visual QA (deterministic offline tier)
      -> candidate + identities

The worker holds no platform secret, never sees BusinessConfig, a
database, storage or provider credential, runs no contract and cannot
approve or publish: the control plane re-validates everything it returns
(app.worker.intake).
"""

import logging
import shutil
import tempfile
import time
from pathlib import Path

from app.creative.frontend_engine.browser_qa import BrowserQAUnavailableError, run_browser_qa
from app.creative.frontend_engine.sandbox import SandboxError, SandboxRunner
from app.creative.frontend_engine.sandboxed_browser_qa import run_browser_qa_sandboxed
from app.creative.source_adapter.pipeline import plan_csp
from app.creative.source_adapter.plan import AdaptationPlan, PlanDriftError, apply_plan
from app.creative.source_adapter.records import AdapterError
from app.creative.source_adapter.snapshot import snapshot_export
from app.creative.source_adapter.static_artifact import assemble_static_artifact
from app.creative.source_adapter.static_build import StaticBuildError, Toolchain, build_in_sandbox, prepare_dependencies
from app.domain.enums import GenerationFailureKind, GenerationJobKind
from app.publishing.csp_policy import UnsupportedCspRequirementError
from app.worker.protocol import ExecutionRequest, ExecutionResult, VisualQAReport, b64, pack_files, sha256_hex

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


def _make_writable(root: Path) -> None:
    for path in [root, *root.rglob("*")]:
        path.chmod(0o755 if path.is_dir() else 0o644)


def execute_source_adaptation(
    request: ExecutionRequest,
    source: bytes,
    *,
    runner: SandboxRunner,
    toolchain: Toolchain | None = None,
) -> ExecutionResult:
    metadata: dict[str, object] = {
        "runner": runner.name,
        "limits_enforced": runner.limits_enforced(),
        "snapshot_sha256": request.source_sha256,
        "plan_sha256": request.plan_sha256,
    }
    if request.job_kind is not GenerationJobKind.SOURCE_ADAPTATION or request.adaptation_plan is None:
        return _failed(request, GenerationFailureKind.CANDIDATE_REJECTED, "not a source-adaptation request", **metadata)
    if sha256_hex(source) != request.source_sha256:
        return _failed(
            request, GenerationFailureKind.CANDIDATE_REJECTED, "source does not match its SHA-256", **metadata
        )
    try:
        plan = AdaptationPlan.from_dict(dict(request.adaptation_plan))
        if plan.plan_sha256 != request.plan_sha256 or plan.snapshot_zip_sha256 != request.source_sha256:
            raise AdapterError("the plan does not match the job's plan/snapshot identity")
        if plan.csp.get("family") != request.source_family:
            raise AdapterError("the plan was made for another source family")
        csp = plan_csp(plan)
    except (AdapterError, UnsupportedCspRequirementError, TypeError, KeyError, ValueError) as exc:
        return _failed(request, GenerationFailureKind.CANDIDATE_REJECTED, f"invalid plan: {exc}", **metadata)
    if not request.site_origin:
        return _failed(request, GenerationFailureKind.CANDIDATE_REJECTED, "no site origin", **metadata)

    with tempfile.TemporaryDirectory(prefix="gwa-source-job-") as tmp:
        root = Path(tmp)
        (root / "source.zip").write_bytes(source)
        try:
            snapshot = snapshot_export(root / "source.zip", root / "original")
            shutil.copytree(snapshot.root, root / "adapted")
            _make_writable(root / "adapted")
            app = root / "adapted" / snapshot.app_dir
            apply_plan(app, plan)
        except (PlanDriftError, AdapterError, OSError) as exc:
            return _failed(request, GenerationFailureKind.CANDIDATE_REJECTED, f"adaptation refused: {exc}", **metadata)

        started = time.monotonic()
        try:
            tools = toolchain or Toolchain.detect()
            prepare_dependencies(app, tools, frozen=False)
            metadata["install_ms"] = int((time.monotonic() - started) * 1000)
            started = time.monotonic()
            steps = tuple((str(s["label"]), tuple(str(a) for a in s["argv"])) for s in plan.build["sandbox_steps"])
            client = build_in_sandbox(app, tools, runner, steps=steps, output_dir=str(plan.build["output_dir"]))
            metadata["build_ms"] = int((time.monotonic() - started) * 1000)
        except StaticBuildError as exc:
            return _failed(request, GenerationFailureKind.BUILD, str(exc), **metadata)
        except SandboxError as exc:
            kind = GenerationFailureKind.RESOURCE_LIMIT if "timed out" in str(exc) else GenerationFailureKind.BUILD
            return _failed(request, kind, str(exc), **metadata)

        try:
            artifact = assemble_static_artifact(
                client,
                business_id=str(request.business_id),
                api_base_url=request.api_base_url,
                site_origin=request.site_origin,
                csp_extensions=csp,
                locale=str(plan.site.get("locale", "en")),
            )
        except AdapterError as exc:
            return _failed(request, GenerationFailureKind.CANDIDATE_REJECTED, str(exc), **metadata)
    missing = sorted(set(plan.build["expected_pages"]) - set(artifact.files))
    if missing:
        return _failed(request, GenerationFailureKind.BUILD, f"pages missing from the build: {missing}", **metadata)
    metadata["headers_sha256"] = sha256_hex(artifact.files["_headers"])

    report: VisualQAReport | None = None
    if request.run_visual_qa:
        started = time.monotonic()
        try:
            if runner.name == "bubblewrap":
                qa = run_browser_qa_sandboxed(
                    artifact.files, offline_assets={}, capture_screenshots=True, runner=runner
                )
            else:
                qa = run_browser_qa(artifact.files, offline_assets={}, capture_screenshots=True)
        except BrowserQAUnavailableError as exc:
            return _failed(request, GenerationFailureKind.SANDBOX_UNAVAILABLE, str(exc), **metadata)
        metadata["visual_qa_ms"] = int((time.monotonic() - started) * 1000)
        report = VisualQAReport(
            passed=qa.passed,
            findings=[
                {"viewport": f.viewport, "check": f.check, "passed": f.passed, "detail": f.detail} for f in qa.findings
            ],
            blocked_requests=qa.blocked_requests[:200],
            screenshots={name: b64(png) for name, png in qa.screenshots.items()},
        )

    candidate = pack_files(artifact.files)
    logger.info(
        "source-adaptation job executed job_id=%s runner=%s files=%d bytes=%d",
        request.job_id,
        runner.name,
        len(artifact.files),
        len(candidate),
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
