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

import hashlib
import logging
import resource
import shutil
import tempfile
import time
from pathlib import Path

from app.creative.frontend_engine.browser_qa import BrowserQAUnavailableError, run_browser_qa
from app.creative.frontend_engine.sandbox import SandboxError, SandboxRunner, SupervisedProcessRunner
from app.creative.frontend_engine.sandboxed_browser_qa import run_browser_qa_sandboxed
from app.creative.source_adapter.pipeline import plan_csp
from app.creative.source_adapter.plan import AdaptationPlan, PlanDriftError, apply_plan
from app.creative.source_adapter.records import AdapterError
from app.creative.source_adapter.snapshot import snapshot_export
from app.creative.source_adapter.static_artifact import assemble_static_artifact
from app.creative.source_adapter.static_build import StaticBuildError, Toolchain, build_in_sandbox, prepare_dependencies
from app.domain.enums import GenerationFailureKind, GenerationJobKind
from app.publishing.csp_policy import UnsupportedCspRequirementError
from app.worker.preflight import browser_env
from app.worker.protocol import ExecutionRequest, ExecutionResult, VisualQAReport, b64, pack_files, sha256_hex

logger = logging.getLogger(__name__)
# R5.1: the whole job (install + build + assemble + QA) must finish well
# inside the control plane's lease (generation_jobs.DEFAULT_LEASE, 15 min),
# so a slow job fails as a resource limit instead of being presumed lost.
JOB_DEADLINE_SECONDS = 12 * 60


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


def tree_digest(root: Path) -> str:
    """SHA-256 over every file's relative path and bytes (the extracted
    original snapshot must be byte-identical after install and build)."""
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink()):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _children_peak_rss_kb() -> int:
    """High-water RSS (kB) of any terminated child of this worker process
    so far (bun install, the Playwright driver/Chromium) — process-lifetime,
    so a LOWER bound for the current job only when it rose during it."""
    return int(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)


def execute_source_adaptation(
    request: ExecutionRequest,
    source: bytes,
    *,
    runner: SandboxRunner,
    toolchain: Toolchain | None = None,
    deadline_seconds: float = JOB_DEADLINE_SECONDS,
) -> ExecutionResult:
    job_started = time.monotonic()
    deadline = job_started + deadline_seconds
    metadata: dict[str, object] = {
        "runner": runner.name,
        "limits_enforced": runner.limits_enforced(),
        "snapshot_sha256": request.source_sha256,
        "plan_sha256": request.plan_sha256,
        "source_bytes": len(source),
    }
    result = _execute(request, source, runner=runner, toolchain=toolchain, deadline=deadline, metadata=metadata)
    metadata["duration_ms"] = int((time.monotonic() - job_started) * 1000)
    if isinstance(runner, SupervisedProcessRunner) and runner.step_peak_rss_kb:
        metadata["build_peak_rss_kb"] = max(runner.step_peak_rss_kb.values())
    metadata["children_peak_rss_kb_lifetime"] = _children_peak_rss_kb()
    result.metadata = {**metadata, **result.metadata}
    logger.info(
        "source-adaptation job metrics job_id=%s attempt=%d status=%s failure=%s duration_ms=%s "
        "source_bytes=%s source_files=%s artifact_bytes=%s artifact_files=%s build_peak_rss_kb=%s",
        request.job_id,
        request.attempt,
        result.status,
        result.failure_kind.value if result.failure_kind else "-",
        metadata.get("duration_ms"),
        metadata.get("source_bytes"),
        metadata.get("source_files", "-"),
        metadata.get("artifact_bytes", "-"),
        metadata.get("artifact_files", "-"),
        metadata.get("build_peak_rss_kb", "-"),
    )
    return result


def _execute(
    request: ExecutionRequest,
    source: bytes,
    *,
    runner: SandboxRunner,
    toolchain: Toolchain | None,
    deadline: float,
    metadata: dict[str, object],
) -> ExecutionResult:
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

    # Everything of this job lives under ONE fresh directory (source copy,
    # adapted tree, node_modules, step homes, build output), removed on
    # success, failure, timeout or interruption.
    with tempfile.TemporaryDirectory(prefix="gwa-source-job-") as tmp:
        root = Path(tmp)
        (root / "source.zip").write_bytes(source)
        try:
            snapshot = snapshot_export(root / "source.zip", root / "original")
            original_digest = tree_digest(snapshot.root)
            metadata["source_files"] = sum(1 for p in snapshot.root.rglob("*") if p.is_file())
            shutil.copytree(snapshot.root, root / "adapted")
            _make_writable(root / "adapted")
            app = root / "adapted" / snapshot.app_dir
            apply_plan(app, plan)
        except (PlanDriftError, AdapterError, OSError) as exc:
            return _failed(request, GenerationFailureKind.CANDIDATE_REJECTED, f"adaptation refused: {exc}", **metadata)

        started = time.monotonic()
        try:
            tools = toolchain or Toolchain.detect()
            prepare_dependencies(app, tools, frozen=False, timeout=deadline - time.monotonic())
            metadata["install_ms"] = int((time.monotonic() - started) * 1000)
            started = time.monotonic()
            steps = tuple((str(s["label"]), tuple(str(a) for a in s["argv"])) for s in plan.build["sandbox_steps"])
            client = build_in_sandbox(
                app, tools, runner, steps=steps, output_dir=str(plan.build["output_dir"]), deadline=deadline
            )
            metadata["build_ms"] = int((time.monotonic() - started) * 1000)
        except StaticBuildError as exc:
            limited = "deadline" in str(exc) or "timed out" in str(exc)
            kind = GenerationFailureKind.RESOURCE_LIMIT if limited else GenerationFailureKind.BUILD
            return _failed(request, kind, str(exc), **metadata)
        except SandboxError as exc:
            kind = GenerationFailureKind.RESOURCE_LIMIT if "timed out" in str(exc) else GenerationFailureKind.BUILD
            return _failed(request, kind, str(exc), **metadata)
        if sha256_hex((root / "source.zip").read_bytes()) != request.source_sha256 or (
            tree_digest(snapshot.root) != original_digest
        ):
            return _failed(
                request,
                GenerationFailureKind.CANDIDATE_REJECTED,
                "the original snapshot changed during install/build — refusing the result",
                **metadata,
            )

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
    metadata["artifact_files"] = len(artifact.files)
    metadata["artifact_bytes"] = sum(len(data) for data in artifact.files.values())
    missing = sorted(set(plan.build["expected_pages"]) - set(artifact.files))
    if missing:
        return _failed(request, GenerationFailureKind.BUILD, f"pages missing from the build: {missing}", **metadata)
    metadata["headers_sha256"] = sha256_hex(artifact.files["_headers"])

    report: VisualQAReport | None = None
    if request.run_visual_qa:
        started = time.monotonic()
        if started >= deadline:
            return _failed(
                request, GenerationFailureKind.RESOURCE_LIMIT, "no time left for Visual QA before the job deadline"
            )
        try:
            if runner.name == "bubblewrap":
                qa = run_browser_qa_sandboxed(
                    artifact.files, offline_assets={}, capture_screenshots=True, runner=runner
                )
            else:
                with tempfile.TemporaryDirectory(prefix="gwa-qa-home-") as home:
                    qa = run_browser_qa(
                        artifact.files, offline_assets={}, capture_screenshots=True, browser_env=browser_env(Path(home))
                    )
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
