"""v0.2 R4.1 — Visual QA inside the untrusted build zone.

Visual QA executes the GENERATED site's JavaScript in Chromium. That is
untrusted code too, so it runs in the same bubblewrap zone as the build
(app.creative.frontend_engine.sandbox): no inherited environment, a fresh
network namespace (only the in-namespace loopback the local static server
listens on), no filesystem beyond the job workspace plus read-only
interpreter/Chromium, its own PID namespace and resource limits.

Inside the zone, a stdlib-only entry script imports browser_qa.py by path —
never the `app` package, its settings or anything holding a credential.
The business's own assets are supplied by trusted code as bytes (files in
the workspace) and served through Playwright routing; every other request
is aborted and, below that, has no network to reach anyway.

Everything the zone writes back is untrusted: results are parsed strictly,
screenshots must be bounded PNGs, and failures are explicit
(BrowserQAUnavailableError), never a silent pass.
"""

import json
import os
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path

from app.creative.frontend_engine import browser_qa
from app.creative.frontend_engine.browser_qa import (
    DEFAULT_VIEWPORTS,
    BrowserQAFinding,
    BrowserQAResult,
    BrowserQAUnavailableError,
)
from app.creative.frontend_engine.sandbox import SandboxError, SandboxLimits, SandboxRunner, detect_runner
from app.creative.frontend_engine.workspace import allocate_workspace, cleanup_workspace

VISUAL_QA_LIMITS = SandboxLimits(
    wall_timeout_seconds=180,
    cpu_seconds=600,
    memory_bytes=3 * 1024**3,
    max_processes=512,
    address_space_fallback=False,
)
MAX_OFFLINE_ASSET_BYTES = 50 * 1024**2
_MAX_SCREENSHOT_BYTES = 10 * 1024**2
_MAX_RESULT_BYTES = 1024**2
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_QA_DIR = "/qa"

_ENTRY = """
import json, pathlib, sys
sys.path.insert(0, "/qa")
import browser_qa
ws = pathlib.Path("/workspace")
req = json.loads((ws / "request.json").read_text())
site = ws / "site"
files = {p.relative_to(site).as_posix(): p.read_bytes() for p in site.rglob("*") if p.is_file() and not p.is_symlink()}
assets = None if req["assets"] is None else {url: (ws / rel).read_bytes() for url, rel in req["assets"].items()}
out = ws / "out"
out.mkdir()
try:
    r = browser_qa.run_browser_qa(
        files,
        viewports=tuple(tuple(v) for v in req["viewports"]),
        capture_screenshots=req["capture"],
        offline_assets=assets,
        probe_script=req.get("probe"),
    )
except browser_qa.BrowserQAUnavailableError as exc:
    (out / "unavailable.txt").write_text(str(exc)[:500])
    sys.exit(3)
for name, png in r.screenshots.items():
    (out / (name + ".png")).write_bytes(png)
(out / "result.json").write_text(json.dumps({
    "findings": [f.__dict__ for f in r.findings],
    "blocked": r.blocked_requests,
    "probes": r.probes,
}))
"""


def _browsers_path() -> Path | None:
    configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if configured and configured != "0":
        return Path(configured)
    default = Path.home() / ".cache" / "ms-playwright"
    return default if default.is_dir() else None


def _interpreter_binds() -> tuple[tuple[str, str], ...]:
    """Read-only: this Python (venv + base install), its site-packages and
    Playwright's browsers. None of these hold secrets or are writable."""
    import playwright

    paths = {Path(sys.prefix), Path(sys.base_prefix), Path(sys.executable).resolve().parent.parent}
    paths.add(Path(playwright.__file__).resolve().parent.parent)
    browsers = _browsers_path()
    if browsers is not None:
        paths.add(browsers)
    keep = sorted(p for p in paths if p.exists() and not str(p).startswith(("/usr", "/bin", "/lib")))
    binds = [(str(p), str(p)) for p in keep]
    if Path("/etc/fonts").is_dir():
        binds.append(("/etc/fonts", "/etc/fonts"))
    return tuple(binds)


def _parse(out: Path, viewports: tuple[tuple[str, int, int], ...]) -> BrowserQAResult:
    result_path = out / "result.json"
    raw = result_path.read_bytes() if result_path.is_file() and not result_path.is_symlink() else b""
    if not raw or len(raw) > _MAX_RESULT_BYTES:
        raise BrowserQAUnavailableError("Sandboxed Visual QA returned no usable result.")
    try:
        data = json.loads(raw)
        findings = [
            BrowserQAFinding(
                viewport=str(f["viewport"])[:50],
                check=str(f["check"])[:80],
                passed=bool(f["passed"]),
                detail=str(f.get("detail", ""))[:500],
            )
            for f in data["findings"]
        ]
        blocked = [str(u)[:300] for u in data.get("blocked", [])][:200]
        probes = list(data.get("probes", []))[:20]
    except (ValueError, KeyError, TypeError) as exc:
        raise BrowserQAUnavailableError("Sandboxed Visual QA returned a malformed result.") from exc
    screenshots: dict[str, bytes] = {}
    for name, _, _ in viewports:
        path = out / f"{name}.png"
        if path.is_file() and not path.is_symlink():
            png = path.read_bytes()
            if len(png) > _MAX_SCREENSHOT_BYTES or not png.startswith(_PNG_MAGIC):
                raise BrowserQAUnavailableError("Sandboxed Visual QA returned an invalid screenshot.")
            screenshots[name] = png
    return BrowserQAResult(findings=findings, screenshots=screenshots, blocked_requests=blocked, probes=probes)


def run_browser_qa_sandboxed(
    files: dict[str, bytes],
    *,
    offline_assets: Mapping[str, bytes] | None = None,
    viewports: tuple[tuple[str, int, int], ...] = DEFAULT_VIEWPORTS,
    capture_screenshots: bool = False,
    probe_script: str | None = None,
    runner: SandboxRunner | None = None,
    limits: SandboxLimits = VISUAL_QA_LIMITS,
) -> BrowserQAResult:
    try:
        runner = runner or detect_runner()
    except SandboxError as exc:
        raise BrowserQAUnavailableError(f"Visual QA cannot run isolated on this host: {exc}") from exc
    # None = no request routing at all: only the network namespace stands
    # between the page and the network (used to prove that layer alone).
    assets = None if offline_assets is None else dict(offline_assets)
    if assets is not None and sum(len(b) for b in assets.values()) > MAX_OFFLINE_ASSET_BYTES:
        raise BrowserQAUnavailableError("Business assets exceed the Visual QA size limit.")

    workspace = allocate_workspace()
    qa_dir = allocate_workspace()
    try:
        shutil.copyfile(browser_qa.__file__, qa_dir / "browser_qa.py")
        (qa_dir / "entry.py").write_text(_ENTRY, encoding="utf-8")
        site = workspace / "site"
        site.mkdir()
        browser_qa._write_files(site, files)
        (workspace / "assets").mkdir()
        asset_map: dict[str, str] | None = None if assets is None else {}
        for index, (url, content) in enumerate((assets or {}).items()):
            (workspace / "assets" / str(index)).write_bytes(content)
            asset_map[url] = f"assets/{index}"  # type: ignore[index]
        request = {
            "viewports": [list(v) for v in viewports],
            "capture": capture_screenshots,
            "assets": asset_map,
            "probe": probe_script,
        }
        (workspace / "request.json").write_text(json.dumps(request), encoding="utf-8")
        env = {"PATH": "/usr/bin:/bin", "HOME": "/tmp", "TMPDIR": "/tmp", "LANG": "C.UTF-8"}
        browsers = _browsers_path()
        if browsers is not None:
            env["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers)
        try:
            runner.run(
                [sys.executable, f"{_QA_DIR}/entry.py"],
                workspace=workspace,
                env=env,
                limits=limits,
                step="visual QA",
                ro_binds=(*_interpreter_binds(), (str(qa_dir), _QA_DIR)),
            )
        except SandboxError as exc:
            raise BrowserQAUnavailableError(f"Sandboxed Visual QA failed: {exc}") from exc
        return _parse(workspace / "out", viewports)
    finally:
        cleanup_workspace(workspace)
        cleanup_workspace(qa_dir)
