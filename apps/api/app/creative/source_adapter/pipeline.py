"""The source-adapter pipeline (H2): a supervised exported website becomes
an immutable GWA WebsiteArtifact through a versioned source-family adapter.

    export ZIP
      -> snapshot_export     immutable, hash-identified ORIGINAL (read-only)
      -> inspect_source      SourceManifest (static, deterministic, bound to
                             the snapshot SHA-256) — nothing executed
      -> select_adapter      exactly one source-family adapter, or UNSUPPORTED
      -> forms / facts       FormMapping per live form; BusinessTruth
                             discovery; claim reconciliation
      -> classify            SUPPORTED | SUPPORTED_WITH_REVIEW | UNSUPPORTED;
                             STOP here (nothing mutated) unless every finding
                             is resolved or approved
      -> plan                AdaptationPlan dry-run on an in-memory copy:
                             every operation with its before/after SHA-256
      -> apply_plan          the same operations on the working copy, with
                             drift detection (the original is never touched)
      -> prepare_dependencies trusted `bun install --ignore-scripts`
      -> build_in_sandbox    the adapter's BuildSpec in the R4 sandbox
      -> assemble_static_artifact  platform runtime, robots/sitemap, _headers
      -> PlatformContract + TruthContract (unmodified)
      -> artifact_sha256 / pack_artifact (the Build Once conventions)

`plan_export` stops after the plan (no install, no build, no execution of
the export's code); `adapt_export` runs everything. Nothing here uploads,
publishes or talks to any provider.
"""

import json
import re
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from app.creative.frontend_engine.sandbox import SandboxRunner, detect_runner
from app.creative.source_adapter import platform_files as pf
from app.creative.source_adapter.adapters import select_adapter
from app.creative.source_adapter.adapters.base import PlanContext, SiteContext
from app.creative.source_adapter.classify import Finding, Supportability, classify
from app.creative.source_adapter.facts import discover_facts, reconcile_claims
from app.creative.source_adapter.forms import FormField, FormInfo, FormMapping, FormOption, FormTransport, map_form
from app.creative.source_adapter.manifest import SourceManifest, inspect_source, write_manifest
from app.creative.source_adapter.overlays import overlay_for
from app.creative.source_adapter.plan import (
    PLAN_VERSION,
    PLATFORM_INTEGRATION_VERSION,
    AdaptationPlan,
    PlanBuilder,
    PlanRefusedError,
    VirtualTree,
    apply_plan,
    canonical_json,
)
from app.creative.source_adapter.records import AdapterError, sha256_hex
from app.creative.source_adapter.snapshot import SourceSnapshot, snapshot_export
from app.creative.source_adapter.static_artifact import assemble_static_artifact
from app.creative.source_adapter.static_build import Toolchain, build_in_sandbox, prepare_dependencies
from app.domain.business_config import BusinessConfig
from app.domain.business_truth import BusinessTruth, derive_business_truth
from app.publishing.artifact_store import artifact_sha256, pack_artifact, unpack_artifact
from app.publishing.csp_policy import validate_requested
from app.publishing.security_headers import CspExtensions
from app.qa.platform_contract import validate_platform_contract
from app.qa.truth_contract import validate_truth_contract

_EXTERNAL_ANCHOR = re.compile(r"<a\b([^>]*\bhref\s*=\s*\"(?:https?:)?//[^\"]*\"[^>]*)>", re.IGNORECASE)
_PLATFORM_FILES = frozenset({"_headers", "robots.txt", "sitemap.xml"})


def form_info(data: dict) -> FormInfo:
    """FormInfo from its manifest dict."""
    fields = tuple(FormField(**{**f, "options": tuple(FormOption(**o) for o in f["options"])}) for f in data["fields"])
    return FormInfo(
        form_id=data["form_id"],
        module=data["module"],
        index=data["index"],
        fields=fields,
        transport=FormTransport(**data["transport"]),
        has_submit_handler=data["has_submit_handler"],
        honeypot_present=data["honeypot_present"],
        already_wired=data["already_wired"],
    )


def external_links(files: dict[str, bytes]) -> list[dict[str, object]]:
    """Every external <a> in the artifact and whether a new-tab link is safe."""
    links: list[dict[str, object]] = []
    for path, data in sorted(files.items()):
        if not path.endswith(".html"):
            continue
        for match in _EXTERNAL_ANCHOR.finditer(data.decode("utf-8", errors="ignore")):
            attrs = match.group(1)
            new_tab = 'target="_blank"' in attrs
            links.append({"page": path, "new_tab": new_tab, "safe": not new_tab or "noopener" in attrs})
    return links


def asset_provenance(files: dict[str, bytes], *, snapshot_files: dict[str, str], app_dir: str) -> dict:
    """Where every artifact file comes from. An export asset must be
    byte-identical to the immutable snapshot's public/ file (same SHA-256),
    so the artifact provably persists the ORIGINAL media; everything else is
    labelled by origin."""
    counts: dict[str, int] = {}
    media: list[dict[str, str]] = []
    prefix = f"{app_dir}/" if app_dir not in ("", ".") else ""
    for path, data in sorted(files.items()):
        digest = sha256_hex(data)
        if snapshot_files.get(f"{prefix}public/{path}") == digest:
            origin = "higgsfield-export"
        elif path in _PLATFORM_FILES:
            origin = "gwa-platform"
        elif path == "og-image.jpg":
            origin = "gwa-derived"
        elif path.endswith((".woff", ".woff2")):
            origin = "self-hosted-ofl-font"
        else:
            origin = "build-output"
        counts[origin] = counts.get(origin, 0) + 1
        if origin != "build-output":
            media.append({"path": path, "origin": origin, "sha256": digest})
    return {"counts": counts, "files": media}


def _make_writable(root: Path) -> None:
    for path in [root, *root.rglob("*")]:
        path.chmod(0o755 if path.is_dir() else 0o644)


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def _csp_dict(csp: CspExtensions) -> dict:
    return {
        "media_blob": csp.media_blob,
        "style_origins": list(csp.style_origins),
        "font_origins": list(csp.font_origins),
    }


def plan_csp(plan: AdaptationPlan) -> CspExtensions:
    """The family policy for the plan's requirements, re-validated (fail closed)."""
    requested = plan.csp["requested"]
    return validate_requested(
        plan.csp["family"],
        CspExtensions(
            media_blob=requested["media_blob"],
            style_origins=tuple(requested["style_origins"]),
            font_origins=tuple(requested["font_origins"]),
        ),
    )


@dataclass
class Planned:
    """Everything decided before the source is mutated."""

    snapshot: SourceSnapshot
    manifest: SourceManifest
    supportability: Supportability
    plan: AdaptationPlan
    truth: BusinessTruth


def plan_export(
    zip_path: Path,
    work_root: Path,
    business_config: BusinessConfig,
    *,
    site_origin: str,
    fact_ledger: dict[str, str] | None = None,
) -> Planned:
    """Snapshot -> inspect -> classify -> plan. Writes source-inventory.json,
    source-manifest.json, supportability.json and adaptation-plan.json into
    `work_root` (which must not exist). Never mutates, installs or builds;
    raises PlanRefusedError (after writing the reports) when not adaptable."""
    if work_root.exists():
        raise AdapterError(f"work root already exists: {work_root}")
    work_root.mkdir(parents=True)
    snapshot = snapshot_export(zip_path, work_root / "original")
    _write_json(work_root / "source-inventory.json", snapshot.manifest())
    app = snapshot.root / snapshot.app_dir
    manifest = inspect_source(app, snapshot_zip_sha256=snapshot.zip_sha256, app_dir=snapshot.app_dir)
    write_manifest(manifest, work_root / "source-manifest.json")

    truth = derive_business_truth(business_config=business_config)
    tree = VirtualTree.from_dir(app)
    adapter = select_adapter(manifest)
    overlay = overlay_for(snapshot.zip_sha256)
    extra: list[Finding] = []
    mappings: list[FormMapping] = []
    facts = None
    locale = "en"
    if adapter is not None:
        locale = adapter.locale(manifest, tree)
        service_ids = {s.id for s in truth.services}
        for form in (f for f in manifest.forms if f["live"] and "error" not in f):
            mapping = map_form(form_info(form), service_ids)
            mappings.append(mapping)
            extra += [Finding(f["code"], f["severity"], f["subject"], f["detail"], "forms") for f in mapping.findings]
        facts = discover_facts(tree, adapter.text_paths(manifest, tree), truth, locale=locale, ledger=fact_ledger)
        extra += [Finding(f["code"], f["severity"], f["subject"], f["detail"], "facts") for f in facts.findings]
        claims = reconcile_claims(manifest.claims, truth)
        extra += [Finding(f["code"], f["severity"], f["subject"], f["detail"], "claims") for f in claims]
    supportability = classify(manifest, adapter, tree, extra, overlay)
    _write_json(work_root / "supportability.json", supportability.to_dict())
    if adapter is None or facts is None or not supportability.ready_to_adapt:
        open_ids = [f.id for f in supportability.open_findings()]
        raise PlanRefusedError(f"{supportability.status}: nothing was modified; open findings: {open_ids}")

    requested = adapter.csp_requirements(manifest, tree)
    applied = validate_requested(adapter.family, requested)  # fail closed
    site = SiteContext(origin=site_origin.rstrip("/"), locale=locale)
    builder = PlanBuilder(VirtualTree(dict(tree)), origin=f"family:{adapter.adapter_id}@{adapter.version}")
    context = PlanContext(manifest, builder.tree, app, truth, site, overlay, mappings, facts)
    pages = adapter.plan(context, builder)
    build = adapter.build_spec(manifest, pages)
    readiness = pf.readiness(
        truth,
        has_generated_icons=any(b["kind"] == "favicon" for b in manifest.brand_assets),
        third_party_services=tuple(sorted({f["family"] for f in manifest.fonts if f["provider"] == "fontshare"})),
        owner_review_claims=overlay.owner_review_claims if overlay else (),
        unverified_claims=[f.to_dict() for f in supportability.findings if f.code == "unverified_factual_claim"],
    )
    decisions = [{"id": f.id, "approval": f.approval} for f in supportability.findings if f.approval]
    decisions += [
        {"id": f.id, "resolution": f.resolution}
        for f in supportability.findings
        if f.resolution and f.severity != "info"
    ]
    plan = AdaptationPlan(
        plan_version=PLAN_VERSION,
        platform_integration_version=PLATFORM_INTEGRATION_VERSION,
        adapter={
            "adapter_id": adapter.adapter_id,
            "version": adapter.version,
            "contract_version": adapter.contract_version,
            "family": adapter.family,
        },
        overlay=None if overlay is None else {"name": overlay.name, "reviewed": overlay.reviewed},
        snapshot_zip_sha256=snapshot.zip_sha256,
        manifest_sha256=manifest.sha256,
        business_truth_sha256=sha256_hex(canonical_json(truth.model_dump(mode="json"))),
        site=asdict(site),
        supportability=supportability.to_dict(),
        form_mappings=[m.to_dict() for m in mappings],
        fact_bindings=[b.to_dict() for b in facts.bindings],
        fact_ledger=facts.ledger,
        # What THIS source needs, and the family policy `_headers` is derived
        # from (H1.1: the family is the unit of trust; intake re-derives the
        # same policy). `requested` is always inside `applied`.
        csp={"family": adapter.family, "requested": _csp_dict(requested), "applied": _csp_dict(applied)},
        build=build.to_dict(),
        approvals=decisions,
        readiness_findings=readiness,
        operations=builder.operations,
        source_tree_sha256=tree.tree_sha256(),
        adapted_tree_sha256=builder.tree.tree_sha256(),
    )
    plan.summary = {
        "operations": len(plan.operations),
        "by_category": {
            c: sum(op.category == c for op in plan.operations) for c in sorted({op.category for op in plan.operations})
        },
        "by_origin": {
            o: sum(op.origin == o for op in plan.operations) for o in sorted({op.origin for op in plan.operations})
        },
        "files_changed": len(plan.changed_files()),
        "visible": [{"op": op.op_id, "path": op.path, "visible": op.visible} for op in plan.operations if op.visible],
        "pages": list(pages),
    }
    _write_json(work_root / "adaptation-plan.json", {**plan.to_dict(), "plan_sha256": plan.plan_sha256})
    return Planned(snapshot, manifest, supportability, plan, truth)


def adapt_export(
    zip_path: Path,
    work_root: Path,
    business_config: BusinessConfig,
    *,
    business_id: str,
    api_base_url: str,
    site_origin: str,
    runner: SandboxRunner | None = None,
    toolchain: Toolchain | None = None,
    fact_ledger: dict[str, str] | None = None,
) -> dict:
    """The whole pipeline into `work_root`; returns the report (also written
    to work_root/report.json)."""
    planned = plan_export(zip_path, work_root, business_config, site_origin=site_origin, fact_ledger=fact_ledger)
    plan, snapshot, manifest = planned.plan, planned.snapshot, planned.manifest
    adapted_root = work_root / "adapted"
    shutil.copytree(snapshot.root, adapted_root)
    _make_writable(adapted_root)
    app = adapted_root / snapshot.app_dir
    changes = apply_plan(app, plan)
    _write_json(work_root / "changes.json", [asdict(c) for c in changes])

    toolchain = toolchain or Toolchain.detect()
    started = time.monotonic()
    prepare_dependencies(app, toolchain, frozen=False)
    install_seconds = round(time.monotonic() - started, 1)
    runner = runner or detect_runner()
    started = time.monotonic()
    steps = tuple((s["label"], tuple(s["argv"])) for s in plan.build["sandbox_steps"])
    client = build_in_sandbox(app, toolchain, runner, steps=steps, output_dir=plan.build["output_dir"])
    build_seconds = round(time.monotonic() - started, 1)

    artifact = assemble_static_artifact(
        client,
        business_id=business_id,
        api_base_url=api_base_url,
        site_origin=site_origin,
        csp_extensions=plan_csp(plan),
        locale=plan.site["locale"],
    )
    missing = sorted(set(plan.build["expected_pages"]) - set(artifact.files))
    if missing:
        raise AdapterError(f"the artifact lacks the pages its BuildSpec promises: {missing}")
    platform = validate_platform_contract(artifact.files, business_config=business_config)
    truth_result = validate_truth_contract(artifact.files, business_truth=planned.truth)
    sha256 = artifact_sha256(artifact)
    archive = pack_artifact(artifact)
    if artifact_sha256(unpack_artifact(archive)) != sha256 or pack_artifact(unpack_artifact(archive)) != archive:
        raise AdapterError("the packed artifact does not round-trip to the same identity")
    (work_root / "artifact.tar.gz").write_bytes(archive)
    ready = platform.passed and truth_result.passed
    readiness = plan.readiness_findings
    report = {
        "adapter": plan.adapter,
        "overlay": plan.overlay,
        "source_family": plan.csp["family"],
        "source": {
            "zip_sha256": snapshot.zip_sha256,
            "files": len(snapshot.files),
            "bytes": sum(f.size for f in snapshot.files),
            "package_manager": snapshot.package_manager,
            "lockfile_sha256": snapshot.lockfile_sha256,
            "build_command": snapshot.build_command,
            "framework": snapshot.framework,
        },
        "manifest": manifest.summary(),
        "supportability": {k: v for k, v in plan.supportability.items() if k != "findings"},
        "plan": {"plan_sha256": plan.plan_sha256, **plan.summary},
        "form_mappings": plan.form_mappings,
        "fact_bindings": plan.fact_bindings,
        "headers_sha256": sha256_hex(artifact.files["_headers"]),
        "install_seconds": install_seconds,
        "build": {
            "seconds": build_seconds,
            "runner": runner.name,
            "limits_enforced": runner.limits_enforced(),
            "steps": plan.build["sandbox_steps"],
        },
        "artifact": {
            "sha256": sha256,
            "archive_sha256": sha256_hex(archive),
            "archive_bytes": len(archive),
            "files": len(artifact.files),
            "bytes": sum(len(v) for v in artifact.files.values()),
            "html_pages": sorted(p for p in artifact.files if p.endswith(".html")),
            "external_links": external_links(artifact.files),
        },
        "platform_contract": {
            "version": platform.version,
            "passed": platform.passed,
            "findings": [f.model_dump(mode="json") for f in platform.findings],
        },
        "truth_contract": {
            "version": truth_result.version,
            "passed": truth_result.passed,
            "findings": [f.model_dump(mode="json") for f in truth_result.findings],
        },
        "ready": ready,
        # Owner/legal input still needed for a real launch (separate from
        # artifact validity, which is the contracts' verdict above).
        "readiness_findings": readiness,
        "launch_ready": ready and not any(f["severity"] == "launch_blocker" for f in readiness),
        "asset_provenance": asset_provenance(
            artifact.files, snapshot_files={f.path: f.sha256 for f in snapshot.files}, app_dir=snapshot.app_dir
        ),
    }
    _write_json(work_root / "report.json", report)
    return report
