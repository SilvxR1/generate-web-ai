"""H1.1 — source-family CSP propagation and artifact-faithful Visual QA.

The policy a site is served with is DERIVED once (frontend_engine.build.
artifact_headers) from its final HTML, its public API origin and its
trusted source family (app.publishing.csp_policy). The build, trusted
intake and the source adapter share that derivation; Visual QA serves the
artifact with those exact `_headers`; preview and production deploy the
stored bytes. Intake-level tests (job family, stored == exercised) live
with the R4.1 fixtures in tests/test_v0_2_r4_1_execution_host.py.
"""

import dataclasses
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

from app.creative.frontend_engine.browser_qa import _serve_directory, _write_files, parse_headers_file, run_browser_qa
from app.creative.frontend_engine.build import artifact_headers, inline_script_hashes
from app.creative.source_adapter.mapping import resolved_csp
from app.creative.source_adapter.mappings.nexo_reformas import MAPPING
from app.domain.enums import GenerationFailureKind
from app.publishing.cloudflare.engine import (
    CloudflarePagesPreviewPublisher,
    CloudflarePagesPublisher,
    preview_branch_for,
)
from app.publishing.csp_policy import (
    DEFAULT_SOURCE_FAMILY,
    SourceFamily,
    UnsupportedCspRequirementError,
    assert_permitted,
    policy_for,
    validate_requested,
)
from app.publishing.publisher import WebsiteArtifact
from app.publishing.security_headers import CspExtensions, generate_headers_file
from app.worker.executor import execute
from app.worker.protocol import ExecutionRequest, b64, pack_files, sha256_hex

API = "https://api.example.com"
HIGGSFIELD = "higgsfield-tanstack-static"
_FONTSHARE = CspExtensions(style_origins=("https://api.fontshare.com",), font_origins=("https://cdn.fontshare.com",))


def _rules(headers: bytes) -> dict[str, str]:
    return dict(parse_headers_file(headers))


def _directives(csp: str) -> dict[str, str]:
    return dict(part.strip().split(" ", 1) for part in csp.split(";"))


# --- Policy: allowlisted, typed, fail closed ------------------------------------


def test_the_baseline_family_adds_nothing():
    assert DEFAULT_SOURCE_FAMILY is SourceFamily.GWA_ASTRO
    assert policy_for("gwa-astro") == CspExtensions()


def test_the_higgsfield_family_policy_is_exactly_blob_media_and_fontshare():
    assert policy_for(HIGGSFIELD) == CspExtensions(
        media_blob=True, style_origins=("https://api.fontshare.com",), font_origins=("https://cdn.fontshare.com",)
    )


@pytest.mark.parametrize("family", ["", "unknown", "GWA-ASTRO", "higgsfield"])
def test_an_unknown_family_fails_closed(family):
    with pytest.raises(UnsupportedCspRequirementError):
        policy_for(family)


def test_a_source_may_request_a_subset_of_its_family_policy():
    assert validate_requested(HIGGSFIELD, CspExtensions(media_blob=True)) == policy_for(HIGGSFIELD)


@pytest.mark.parametrize(
    ("family", "requested"),
    [
        ("gwa-astro", CspExtensions(media_blob=True)),
        ("gwa-astro", _FONTSHARE),
        (HIGGSFIELD, CspExtensions(style_origins=("https://fonts.googleapis.com",))),
        (HIGGSFIELD, CspExtensions(font_origins=("https://evil.example",))),
    ],
)
def test_a_request_beyond_the_family_policy_fails_closed(family, requested):
    with pytest.raises(UnsupportedCspRequirementError):
        validate_requested(family, requested)


@pytest.mark.parametrize(
    "origin",
    [
        "'unsafe-inline'",
        "'unsafe-eval'",
        "*",
        "https://*.fontshare.com",
        "https:",
        "http://api.fontshare.com",
        "blob:",
        "data:",
        "https://api.fontshare.com/css",
    ],
)
def test_unsafe_sources_cannot_even_be_expressed(origin):
    with pytest.raises(ValueError):
        CspExtensions(style_origins=(origin,))


def test_a_family_policy_outside_the_platform_allowlist_is_refused():
    with pytest.raises(UnsupportedCspRequirementError):
        assert_permitted(SourceFamily.HIGGSFIELD_TANSTACK, CspExtensions(font_origins=("https://fonts.example",)))
    with pytest.raises(UnsupportedCspRequirementError):
        assert_permitted(SourceFamily.GWA_ASTRO, CspExtensions(media_blob=True))


# --- One derivation ---------------------------------------------------------------


def test_artifact_headers_is_the_unchanged_baseline_for_gwa_astro():
    html = "<html><head></head><body><script>boot()</script></body></html>"
    assert artifact_headers(
        {"index.html": html.encode(), "a.js": b"x"}, api_base_url=API, csp_extensions=policy_for("gwa-astro")
    ) == generate_headers_file(script_hashes=inline_script_hashes([html]), public_api_origin=API)


def test_higgsfield_headers_extend_only_media_style_and_font_and_keep_every_other_header():
    files = {"index.html": b"<html><body><script>boot()</script></body></html>"}
    base = _rules(artifact_headers(files, api_base_url=API, csp_extensions=policy_for("gwa-astro")))
    fam = _rules(artifact_headers(files, api_base_url=API, csp_extensions=policy_for(HIGGSFIELD)))
    # X-Frame-Options, HSTS, nosniff, Referrer/Permissions-Policy: unchanged.
    assert {k: v for k, v in base.items() if k != "Content-Security-Policy"} == {
        k: v for k, v in fam.items() if k != "Content-Security-Policy"
    }
    base_csp, fam_csp = _directives(base["Content-Security-Policy"]), _directives(fam["Content-Security-Policy"])
    assert {name for name in fam_csp if fam_csp[name] != base_csp.get(name)} == {"media-src", "style-src", "font-src"}
    assert fam_csp["media-src"] == "'self' blob:"
    assert fam_csp["style-src"] == "'self' 'unsafe-inline' https://api.fontshare.com"
    assert fam_csp["font-src"] == "'self' https://fonts.gstatic.com https://cdn.fontshare.com data:"
    assert fam_csp["script-src"] == base_csp["script-src"]
    assert "unsafe-eval" not in fam["Content-Security-Policy"]


# --- The execution host --------------------------------------------------------------


class _Runner:
    name = "stub"

    def limits_enforced(self, limits=None):
        return {}


def _request(source_family: str) -> ExecutionRequest:
    archive = pack_files({"src/pages/index.astro": b"<h1>x</h1>"})
    return ExecutionRequest(
        job_id=uuid.uuid4(),
        attempt=1,
        business_id=uuid.uuid4(),
        api_base_url=API,
        source_family=source_family,
        source_archive=b64(archive),
        source_sha256=sha256_hex(archive),
    )


@pytest.mark.parametrize("family", ["unknown-family", HIGGSFIELD])
def test_the_host_refuses_families_it_cannot_build_with_their_policy(family):
    result = execute(_request(family), runner=_Runner())  # type: ignore[arg-type]
    assert result.status == "failed" and result.failure_kind is GenerationFailureKind.CANDIDATE_REJECTED
    assert result.candidate_archive is None


# --- Visual QA serves the artifact's own `_headers` ----------------------------------


def test_the_qa_server_applies_the_headers_file_and_never_serves_it(tmp_path):
    headers = artifact_headers({"index.html": b"<p>x</p>"}, api_base_url=API, csp_extensions=policy_for(HIGGSFIELD))
    _write_files(tmp_path, {"index.html": b"<p>x</p>", "_headers": headers})
    with _serve_directory(tmp_path) as port:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as response:  # noqa: S310 — local test server
            assert response.headers["Content-Security-Policy"] == _rules(headers)["Content-Security-Policy"]
            assert response.headers["X-Frame-Options"] == "DENY"
        with pytest.raises(urllib.error.HTTPError) as blocked:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/_headers")  # noqa: S310
        assert blocked.value.code == 404


def _qa(files: dict[str, bytes], probe: str | None = None):
    result = run_browser_qa(files, viewports=(("desktop", 1024, 768),), probe_script=probe)
    return {f.check: f for f in result.findings if f.viewport == "desktop"}, result.probes


_PAGE = "<!doctype html><html><head><title>t</title></head><body><h1>x</h1>{body}</body></html>"


def test_visual_qa_enforces_the_artifact_csp_and_reports_violations():
    page = _PAGE.format(body="<script>window.__ran = 1</script>").encode()
    no_hash = generate_headers_file(public_api_origin=API)  # does NOT allow this inline script
    findings, probes = _qa({"index.html": page, "_headers": no_hash}, probe="window.__ran === 1")
    assert findings["artifact_csp_applied"].passed
    assert not findings["no_csp_violations"].passed and "script-src" in findings["no_csp_violations"].detail
    assert probes == [False]  # the browser really blocked it


def test_visual_qa_passes_a_script_containing_nul_under_the_derived_policy():
    # TanStack Start's dehydrated state embeds U+0000; the browser hashes it as
    # U+FFFD. artifact_headers must hash exactly that, or the real CSP blocks it.
    page = _PAGE.format(body='<script>window.__ran = "a\x00b".length</script>').encode()
    headers = artifact_headers({"index.html": page}, api_base_url=API, csp_extensions=policy_for("gwa-astro"))
    findings, probes = _qa({"index.html": page, "_headers": headers}, probe="window.__ran === 3")
    assert findings["artifact_csp_applied"].passed
    assert findings["no_csp_violations"].passed, findings["no_csp_violations"].detail
    assert probes == [True]


def test_visual_qa_reports_failed_same_origin_resources():
    page = _PAGE.format(body="<img src='/missing.png' alt=''>").encode()
    findings, _ = _qa({"index.html": page})
    assert not findings["no_failed_resources"].passed and "/missing.png" in findings["no_failed_resources"].detail


# --- Preview and production deploy the stored `_headers` -------------------------------


def test_preview_and_production_deploy_the_stored_headers_byte_for_byte(monkeypatch):
    deployed: list[dict[str, bytes]] = []

    class _Completed:
        returncode, stdout, stderr = 0, "ok", ""

    def fake_run(args, **kwargs):
        directory = Path(args[args.index("deploy") + 1])
        uploaded = {p.relative_to(directory).as_posix(): p.read_bytes() for p in directory.rglob("*") if p.is_file()}
        deployed.append(uploaded)
        return _Completed()

    class _Client:
        def ensure_project(self, project_name):
            pass

        def get_project(self, project_name):
            return {"latest_deployment": {"id": "dep-1"}}

        def list_deployments(self, project_name):
            trigger = {"metadata": {"branch": branch}}
            return [{"id": "cf-1", "url": f"https://abcd.{project_name}.pages.dev", "deployment_trigger": trigger}]

    monkeypatch.setattr("app.publishing.cloudflare.engine.subprocess.run", fake_run)
    branch = preview_branch_for(uuid.uuid4())
    files = {"index.html": b"<html><body><script>boot()</script></body></html>", "assets/a.js": b"x"}
    files["_headers"] = artifact_headers(files, api_base_url=API, csp_extensions=policy_for(HIGGSFIELD))
    stored = WebsiteArtifact(files=files, entry_point="index.html")

    CloudflarePagesPreviewPublisher(_Client(), account_id="a", api_token="t").publish_preview(  # type: ignore[arg-type]
        branch=branch, artifact=stored
    )
    CloudflarePagesPublisher(_Client(), account_id="a", api_token="t").publish(  # type: ignore[arg-type]
        site_id="site-1", artifact=stored
    )
    assert len(deployed) == 2
    for uploaded in deployed:
        assert uploaded == stored.files  # `_headers` included, nothing re-derived or injected
        assert "media-src 'self' blob:" in uploaded["_headers"].decode()


# --- The Higgsfield source adapter ---------------------------------------------------------


def test_the_nexo_mapping_resolves_to_its_family_policy():
    assert resolved_csp(MAPPING) == policy_for(HIGGSFIELD)


def test_an_adapter_mapping_that_over_reaches_fails_closed():
    greedy = dataclasses.replace(MAPPING, csp_requirements=CspExtensions(style_origins=("https://fonts.googleapis.com",)))
    with pytest.raises(UnsupportedCspRequirementError):
        resolved_csp(greedy)
    with pytest.raises(UnsupportedCspRequirementError):
        resolved_csp(dataclasses.replace(MAPPING, source_family="gwa-astro"))
