"""v0.2 R4 — ISOLATED GENERATION WORKER (local/CI evidence).

    Untrusted generated code must never execute inside the trusted API
    process or with access to platform secrets.

Every attack below runs as REAL Node.js inside the real untrusted build zone
(app.creative.frontend_engine.sandbox) — the same runner build.py uses for
`astro build` — and must be contained. These prove what THIS host enforces;
they say nothing about the production host (see the R4 architecture section).
No provider, no production, no external network is ever reached: the attacks
that try the network are proven unable to leave the sandbox.
"""

import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.creative import generation_jobs as jobs
from app.creative.frontend_engine import build as generative_build
from app.creative.frontend_engine import sandbox as sandbox_module
from app.creative.frontend_engine.build import (
    GenerativeBuildError,
    build_generative_workspace,
    collect_candidate_files,
)
from app.creative.frontend_engine.sandbox import (
    SandboxError,
    SandboxLimits,
    SandboxUnavailableError,
    detect_runner,
)
from app.creative.frontend_engine.templates import build_package_json, vetted_lockfile
from app.creative.frontend_engine.workspace import allocate_workspace, cleanup_workspace
from app.db.models import Business
from app.domain.enums import BusinessStatus, BusinessVertical, GenerationFailureKind, GenerationJobStatus
from app.qa.truth_contract import validate_truth_contract
from tests import test_v0_2_r2_feature_parity as _r2

built = _r2.built  # the real free-form R2 build — now necessarily sandboxed

SENTINEL = "r4-sentinel-must-never-leak"
_NODE_DIR = str(Path(shutil.which("node") or "/usr/bin/node").resolve().parent)
_ENV = {"PATH": f"{_NODE_DIR}:/usr/bin:/bin", "HOME": "/tmp", "TMPDIR": "/tmp", "LANG": "C.UTF-8"}
_FAST = SandboxLimits(wall_timeout_seconds=30)
API_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def runner():
    return detect_runner()  # no skip: a host that cannot sandbox must FAIL this suite, not pass it


@pytest.fixture()
def ws():
    workspace = allocate_workspace()
    try:
        yield workspace
    finally:
        cleanup_workspace(workspace)


def _attack(runner, ws: Path, js: str, limits: SandboxLimits = _FAST) -> dict:
    """Runs `js` as untrusted Node.js in the build zone; the script records
    what it managed to do in /workspace/result.json."""
    (ws / "attack.js").write_text(
        "const fs=require('fs'),net=require('net');const out={};"
        "const save=()=>fs.writeFileSync('/workspace/result.json',JSON.stringify(out));" + js
    )
    runner.run(["node", "attack.js"], workspace=ws, env=_ENV, limits=limits, step="attack")
    return json.loads((ws / "result.json").read_text())


def _try_read(path: str) -> str:
    key = json.dumps(path)
    return f"try{{fs.readFileSync({key});out[{key}]='READ'}}catch(e){{out[{key}]=e.code}};"


def _try_write(path: str) -> str:
    key = json.dumps(path)
    return f"try{{fs.writeFileSync({key},'x');out[{key}]='WROTE'}}catch(e){{out[{key}]=e.code}};"


# --- Environment ------------------------------------------------------------------------


def test_platform_secrets_in_the_api_environment_never_reach_generated_code(runner, ws, monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "DATABASE_URL", "R2_SECRET_ACCESS_KEY", "CLOUDFLARE_API_TOKEN"):
        monkeypatch.setenv(name, SENTINEL)
    out = _attack(
        runner,
        ws,
        "out.env=process.env;out.procs={};"
        "for(const p of fs.readdirSync('/proc').filter(x=>/^\\d+$/.test(x))){"
        "try{out.procs[p]=fs.readFileSync('/proc/'+p+'/environ','latin1')}catch(e){out.procs[p]=e.code}}save()",
    )
    assert SENTINEL not in json.dumps(out)
    assert set(out["env"]) <= {*_ENV, "PWD"}  # PWD=/workspace is set by bwrap --chdir
    # PID namespace: only the sandbox's own couple of processes exist — the API is not even visible.
    assert len(out["procs"]) <= 3, out["procs"].keys()


# --- Filesystem -------------------------------------------------------------------------


def test_generated_code_cannot_read_outside_its_workspace(runner, ws, tmp_path):
    secret = tmp_path / "outside.txt"
    secret.write_text(SENTINEL)
    targets = [str(secret), str(API_ROOT / "app" / "config.py"), str(Path.home()), "/etc/passwd", "/root"]
    out = _attack(runner, ws, "".join(_try_read(t) for t in targets) + "save()")
    assert all(out[t] != "READ" for t in targets), out


def test_generated_code_cannot_write_outside_its_workspace(runner, ws, tmp_path):
    victim = tmp_path / "victim.txt"
    targets = [str(victim), "/usr/pwned", f"{_NODE_DIR}/pwned"]
    out = _attack(runner, ws, "".join(_try_write(t) for t in targets) + "save()")
    assert "WROTE" not in out.values(), out
    assert not victim.exists()


def test_generated_code_cannot_reach_another_jobs_workspace(runner, ws):
    other = allocate_workspace()
    try:
        (other / "index.astro").write_text(SENTINEL)
        target = str(other / "index.astro")
        out = _attack(runner, ws, _try_read(target) + "out.tmp=fs.readdirSync('/tmp');save()")
        assert out[target] != "READ"
        assert not any(name.startswith("gwa-") for name in out["tmp"])  # a private /tmp, not the host's
    finally:
        cleanup_workspace(other)


# --- Network ----------------------------------------------------------------------------


class _Recorder(http.server.BaseHTTPRequestHandler):
    hits: list[str] = []

    def do_GET(self):  # noqa: N802
        self.hits.append(self.path)
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


def _connect_js(host: str, port: int, key: str) -> str:
    k = json.dumps(key)
    return (
        f"await new Promise(r=>{{const s=net.connect({port},{json.dumps(host)});s.setTimeout(3000);"
        f"s.on('connect',()=>{{out[{k}]='CONNECTED';s.destroy();r()}});"
        f"s.on('error',e=>{{out[{k}]=e.code;r()}});"
        f"s.on('timeout',()=>{{out[{k}]='TIMEOUT';s.destroy();r()}})}});"
    )


def test_network_is_denied_local_services_external_hosts_metadata_and_dns(runner, ws):
    server = http.server.HTTPServer(("127.0.0.1", 0), _Recorder)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        out = _attack(
            runner,
            ws,
            "(async()=>{"
            + _connect_js("127.0.0.1", port, "local_api")
            + _connect_js("1.1.1.1", 443, "external")
            + _connect_js("169.254.169.254", 80, "metadata")
            + "await new Promise(r=>require('dns').lookup('example.com',e=>{out.dns=e?e.code:'RESOLVED';r()}));"
            + "out.ifaces=Object.keys(require('os').networkInterfaces());save()})()",
        )
    finally:
        server.shutdown()
    assert "CONNECTED" not in out.values() and out["dns"] != "RESOLVED", out
    assert out["ifaces"] in ([], ["lo"])  # a fresh network namespace: no host interface
    assert _Recorder.hits == []


# --- Process / resources ----------------------------------------------------------------


def test_an_infinite_build_is_killed_at_the_wall_clock_limit(runner, ws):
    (ws / "spin.js").write_text("for(;;){}")
    with pytest.raises(SandboxError, match="timed out"):
        runner.run(["node", "spin.js"], workspace=ws, env=_ENV, limits=SandboxLimits(wall_timeout_seconds=3), step="b")


def test_a_process_explosion_is_contained_and_leaves_nothing_behind(runner, ws):
    marker = f"gwar4{uuid.uuid4().hex[:8]}"
    (ws / "bomb.sh").write_text(f"i=0; while [ $i -lt 1000 ]; do (exec -a {marker} sleep 60) & i=$((i+1)); done; wait")
    limits = SandboxLimits(wall_timeout_seconds=8, max_processes=64)
    with pytest.raises(SandboxError):
        runner.run(["/bin/bash", "bomb.sh"], workspace=ws, env=_ENV, limits=limits, step="b")
    leftover = subprocess.run(["pgrep", "-f", marker], capture_output=True, text=True).stdout.split()
    assert leftover == []  # the whole PID namespace was torn down


def test_memory_is_capped(runner, ws):
    (ws / "hog.js").write_text("const a=[];for(;;)a.push(Buffer.alloc(32<<20,1))")
    limits = SandboxLimits(wall_timeout_seconds=30, memory_bytes=512 * 1024**2)
    with pytest.raises(SandboxError):
        runner.run(["node", "hog.js"], workspace=ws, env=_ENV, limits=limits, step="b")


def test_excessive_output_is_capped(runner, ws):
    (ws / "spam.js").write_text("const b='x'.repeat(1<<20);for(let i=0;i<64;i++)process.stdout.write(b)")
    limits = SandboxLimits(wall_timeout_seconds=30, max_file_bytes=4 * 1024**2)
    with pytest.raises(SandboxError):
        runner.run(["node", "spam.js"], workspace=ws, env=_ENV, limits=limits, step="b")


def test_scratch_disk_is_capped(runner, ws):
    out = _attack(
        runner,
        ws,
        "try{fs.writeFileSync('/tmp/fill',Buffer.alloc(64<<20));out.tmp='WROTE'}catch(e){out.tmp=e.code};save()",
        SandboxLimits(wall_timeout_seconds=30, tmp_bytes=8 * 1024**2),
    )
    assert out["tmp"] == "ENOSPC"


def test_the_sandbox_reports_which_limits_this_host_enforces(runner):
    enforced = runner.limits_enforced()
    assert all(enforced[k] for k in ("wall_timeout", "cpu", "file_size", "tmp_size", "memory"))
    assert "process_count" in enforced  # True only with a cgroup scope — reported, never assumed


# --- Fail closed ------------------------------------------------------------------------


def test_no_bubblewrap_means_no_build_at_all(monkeypatch, ws):
    monkeypatch.setattr(sandbox_module.shutil, "which", lambda name: None)
    with pytest.raises(SandboxUnavailableError):
        detect_runner()
    ran: list = []
    monkeypatch.setattr(generative_build.subprocess, "run", lambda *a, **k: ran.append(a))
    (ws / "package.json").write_text(json.dumps(build_package_json(name="x", additional_dependencies=[])))
    (ws / "package-lock.json").write_text(vetted_lockfile())
    with pytest.raises(GenerativeBuildError, match="bubblewrap is not installed"):
        build_generative_workspace(ws, business_id="b1")
    assert ran == []  # refused before even the trusted install


def test_a_kernel_refusing_namespaces_fails_closed(monkeypatch):
    monkeypatch.setattr(sandbox_module, "_works", lambda cmd: False)
    with pytest.raises(SandboxUnavailableError, match="namespaces are unavailable"):
        detect_runner()


# --- Candidate boundary -----------------------------------------------------------------


def test_candidate_output_file_links_are_never_followed(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>")
    (dist / "leak.txt").symlink_to("/etc/passwd")
    with pytest.raises(GenerativeBuildError, match="symbolic link"):
        collect_candidate_files(dist)


def test_candidate_output_directory_links_are_never_followed(tmp_path):
    other = tmp_path / "other-job"
    other.mkdir()
    (other / "secret.html").write_text(SENTINEL)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>")
    (dist / "assets").symlink_to(other, target_is_directory=True)
    with pytest.raises(GenerativeBuildError, match="symbolic link"):
        collect_candidate_files(dist)


def test_candidate_output_is_bounded(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_bytes(b"x" * 2048)
    monkeypatch.setattr(generative_build, "MAX_CANDIDATE_FILE_BYTES", 1024)
    with pytest.raises(GenerativeBuildError, match="size limit"):
        collect_candidate_files(dist)
    monkeypatch.setattr(generative_build, "MAX_CANDIDATE_FILE_BYTES", 4096)
    monkeypatch.setattr(generative_build, "MAX_CANDIDATE_FILES", 0)
    with pytest.raises(GenerativeBuildError, match="file-count"):
        collect_candidate_files(dist)


def test_a_real_sandboxed_build_is_the_candidate_the_contracts_judge(built):
    """build.py has no unsandboxed path: the R2 free-form fixture's real
    `astro build` ran in the build zone and its candidate still passes."""
    truth, _, artifact = built
    assert "index.html" in artifact.files
    assert validate_truth_contract(artifact.files, business_truth=truth).passed


# --- BASIC and rollback never use the build zone ----------------------------------------


@pytest.mark.parametrize("module", ["app/publishing/build.py", "app/publishing/versions.py"])
def test_basic_builds_and_rollback_never_invoke_the_generative_build_zone(module):
    text = (API_ROOT / module).read_text()
    assert "frontend_engine" not in text and "sandbox" not in text


# --- Job model --------------------------------------------------------------------------


def _submit(session, tenant, business, key="k1", digest="a" * 64):
    return jobs.submit_job(
        session, tenant_id=tenant.id, business_id=business.id, idempotency_key=key, input_sha256=digest
    )


def test_job_submission_is_idempotent(session, tenant, business):
    first = _submit(session, tenant, business)
    assert first.status is GenerationJobStatus.QUEUED
    assert _submit(session, tenant, business).id == first.id
    with pytest.raises(jobs.GenerationJobError, match="different generation request"):
        _submit(session, tenant, business, digest="b" * 64)


def test_a_job_is_claimed_exactly_once(session, tenant, business):
    job = _submit(session, tenant, business)
    claimed = jobs.claim(session, tenant_id=tenant.id, job_id=job.id)
    assert claimed is not None and claimed.status is GenerationJobStatus.RUNNING and claimed.attempts == 1
    assert jobs.claim(session, tenant_id=tenant.id, job_id=job.id) is None


def test_terminal_states_never_transition_and_failures_are_never_retried(session, tenant, business):
    job = jobs.claim(session, tenant_id=tenant.id, job_id=_submit(session, tenant, business).id)
    assert job is not None
    jobs.fail(job, kind=GenerationFailureKind.TRUTH_CONTRACT, error="TruthContract violation(s)")
    assert job.status is GenerationJobStatus.FAILED and job.finished_at is not None
    with pytest.raises(jobs.GenerationJobError, match="illegal"):
        jobs.succeed(job, draft_id=uuid.uuid4())
    with pytest.raises(jobs.GenerationJobError, match="illegal"):
        jobs.fail(job, kind=GenerationFailureKind.BUILD, error="x")
    session.flush()
    assert jobs.claim(session, tenant_id=tenant.id, job_id=job.id) is None  # no hidden (paid) retry
    assert job.attempts == 1


def test_a_lost_worker_fails_its_job_without_rerunning_it(session, tenant, business):
    job = jobs.claim(
        session, tenant_id=tenant.id, job_id=_submit(session, tenant, business).id, lease=timedelta(seconds=1)
    )
    assert job is not None
    assert jobs.expire_lost_jobs(session, now=datetime.now(UTC) + timedelta(minutes=1)) == 1
    assert job.status is GenerationJobStatus.FAILED and job.failure_kind is GenerationFailureKind.WORKER_LOST


def test_jobs_are_tenant_isolated(session, tenant, other_tenant, business):
    job = _submit(session, tenant, business)
    assert jobs.get_job(session, tenant_id=other_tenant.id, job_id=job.id) is None
    assert jobs.claim(session, tenant_id=other_tenant.id, job_id=job.id) is None
    theirs = Business(
        tenant_id=other_tenant.id,
        name="Otra",
        slug="otra",
        vertical=BusinessVertical.HOME_RENOVATION,
        raw_description="x",
        status=BusinessStatus.DRAFT,
    )
    session.add(theirs)
    session.flush()
    # The same idempotency key in another tenant is that tenant's own job.
    assert _submit(session, other_tenant, theirs).id != job.id


def test_r4_migration_is_additive_reversible_and_the_single_head(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'm.db'}"

    def alembic(*args: str) -> str:
        env = {**os.environ, "DATABASE_URL": db_url}
        done = subprocess.run(
            [sys.executable, "-m", "alembic", *args], cwd=API_ROOT, env=env, capture_output=True, text=True, timeout=120
        )
        assert done.returncode == 0, done.stderr
        return done.stdout

    def tables() -> set[str]:
        engine = sa.create_engine(db_url)
        try:
            return set(sa.inspect(engine).get_table_names())
        finally:
            engine.dispose()

    alembic("upgrade", "f1a7c3e9b2d4")
    assert "generation_jobs" not in tables()
    alembic("upgrade", "a4d2e8f1c7b3")
    assert "generation_jobs" in tables()
    alembic("downgrade", "f1a7c3e9b2d4")
    assert "generation_jobs" not in tables()
    alembic("upgrade", "head")
    assert alembic("heads").split() == ["a4d2e8f1c7b3", "(head)"]
