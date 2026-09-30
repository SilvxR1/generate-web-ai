"""PortabilityCleanup (H1): remove an export's dependencies on packages the
export does not contain — deterministically, and only where the public
site provably does not need them.

An exported project may declare `workspace:*` packages that live in the
builder's private monorepo (Higgsfield: @higgsfield/quanta, fnf, fnf-react,
app-landing) and are absent from the export and from the public registry.
The rule, applied to a static import graph of `src/` and `tests/`:

1. A module is TAINTED if it imports an unavailable package, or a tainted
   module (fixed point).
2. A tainted ROUTE is dropped, unless it is the index route or the root
   layout: then the public site needs a private package and the adapter
   STOPS (DesignCriticalDependencyError) — nothing is replaced or stubbed.
   A tainted server/router entry also stops the adapter.
3. Every tainted module NOT reachable from the kept routes/entries is
   removed. (A kept module can never be tainted: taint propagates upward.)
4. CSS (live stylesheets only): `@import`s of unavailable packages,
   `@source` globs pointing to missing directories, and `@import`s of
   stylesheets of DEAD component directories (no module reachable from the
   public site) are removed. Visual QA of the built site is what proves
   dropping them did not change the design.
5. package.json: the unavailable dependencies (and a `workspaces` field
   with no workspace directory left) are removed.

Import resolution is a regex scan (static `import`/`export … from`,
side-effect imports, `import()` with a literal). That is sufficient
because the build that follows (`tsc --noEmit` + bundling) independently
fails on any import this scan missed — a missed import can never silently
ship.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from app.creative.source_adapter.records import AdapterError, ChangeRecord, remove_file, sha256_hex

_IMPORT = re.compile(
    r"""(?:^|[;\s])(?:import|export)\s[^'"`;]*?\bfrom\s*["']([^"']+)["']"""
    r"""|(?:^|[;\s])import\s*["']([^"']+)["']"""
    r"""|\bimport\(\s*["']([^"']+)["']\s*\)""",
    re.MULTILINE,
)
_CSS_IMPORT = re.compile(r'^\s*@import\s+"([^"]+)"[^;\n]*;\s*\n', re.MULTILINE)
_CSS_SOURCE = re.compile(r'^\s*@source\s+"([^"]+)"\s*;\s*\n', re.MULTILINE)
_SOURCE_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs")
_ENTRY_FILES = ("src/server.ts", "src/start.ts", "src/router.tsx")
_PROTECTED_ROUTES = ("src/routes/index.tsx", "src/routes/__root.tsx")


class DesignCriticalDependencyError(AdapterError):
    """The public site itself needs a package the export does not contain."""


@dataclass
class CleanupResult:
    unavailable_packages: list[str]
    removed_routes: list[str] = field(default_factory=list)
    changes: list[ChangeRecord] = field(default_factory=list)


def _unavailable_workspace_packages(app: Path, package: dict) -> list[str]:
    present: set[str] = set()
    for manifest in app.glob("packages/*/package.json"):
        present.add(json.loads(manifest.read_text(encoding="utf-8")).get("name", ""))
    deps = {**package.get("devDependencies", {}), **package.get("dependencies", {})}
    return sorted(name for name, spec in deps.items() if str(spec).startswith("workspace:") and name not in present)


def _module_files(app: Path) -> list[str]:
    return sorted(
        p.relative_to(app).as_posix()
        for base in ("src", "tests")
        for p in (app / base).rglob("*")
        if p.is_file() and p.suffix in _SOURCE_SUFFIXES and p.name != "routeTree.gen.ts"
    )


def _normalize(parts: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for part in parts:
        if part == "..":
            if out:
                out.pop()
        elif part not in (".", ""):
            out.append(part)
    return out


def _resolve(app: Path, importer: str, spec: str) -> str | None:
    spec = spec.split("?", 1)[0]
    if spec.startswith("@/"):
        base = PurePosixPath("src") / spec[2:]
    elif spec.startswith("."):
        base = PurePosixPath(importer).parent / spec
    else:
        return None
    normalized = PurePosixPath(*_normalize(base.parts))
    for candidate in (
        str(normalized),
        *(f"{normalized}{s}" for s in _SOURCE_SUFFIXES),
        *(f"{normalized}/index{s}" for s in _SOURCE_SUFFIXES),
    ):
        if (app / candidate).is_file():
            return candidate
    return None


def _is_unavailable(spec: str, unavailable: list[str]) -> bool:
    return any(spec == name or spec.startswith(f"{name}/") for name in unavailable)


def _graph(app: Path, modules: list[str], unavailable: list[str]) -> tuple[dict[str, set[str]], set[str]]:
    edges: dict[str, set[str]] = {}
    direct: set[str] = set()
    for module in modules:
        text = (app / module).read_text(encoding="utf-8", errors="ignore")
        edges[module] = set()
        for match in _IMPORT.finditer(text):
            spec = next(group for group in match.groups() if group)
            if _is_unavailable(spec, unavailable):
                direct.add(module)
            resolved = _resolve(app, module, spec)
            if resolved is not None and resolved.endswith(_SOURCE_SUFFIXES):
                edges[module].add(resolved)
    return edges, direct


def _tainted(edges: dict[str, set[str]], direct: set[str]) -> set[str]:
    tainted = set(direct)
    changed = True
    while changed:
        changed = False
        for module, targets in edges.items():
            if module not in tainted and targets & tainted:
                tainted.add(module)
                changed = True
    return tainted


def _reachable(edges: dict[str, set[str]], roots: list[str]) -> set[str]:
    seen: set[str] = set()
    stack = list(roots)
    while stack:
        module = stack.pop()
        if module in seen:
            continue
        seen.add(module)
        stack.extend(edges.get(module, ()))
    return seen


@dataclass(frozen=True)
class CssEdit:
    path: str
    before: str
    after: str
    dropped: tuple[str, ...]


def _css_edits(app: Path, unavailable: list[str], modules: list[str], kept: set[str]) -> list[CssEdit]:
    """A component directory is DEAD when it holds source modules but none of
    them is reachable from the public site. Its stylesheets are left alone
    (nothing imports them any more); live stylesheets drop their imports of
    unavailable packages and of dead components' stylesheets (which may
    `@apply` utilities only the unavailable package defined)."""
    kept_dirs = {str(PurePosixPath(m).parent) for m in kept}
    dead_dirs = {str(PurePosixPath(m).parent) for m in modules} - kept_dirs
    edits = []
    for css in sorted(app.glob("src/**/*.css")):
        relative = css.relative_to(app).as_posix()
        css_dir = PurePosixPath(relative).parent
        if str(css_dir) in dead_dirs:
            continue
        text = css.read_text(encoding="utf-8")
        dropped: list[str] = []

        def drop_import(match: re.Match[str], css_dir: PurePosixPath = css_dir, dropped: list[str] = dropped) -> str:
            target = match.group(1)
            if _is_unavailable(target, unavailable):
                dropped.append(match.group(0).strip())
                return ""
            if target.startswith("."):
                target_dir = str(PurePosixPath(*_normalize((css_dir / target).parent.parts)))
                if target_dir in dead_dirs:
                    dropped.append(match.group(0).strip())
                    return ""
            return match.group(0)

        def drop_source(match: re.Match[str], css_dir: PurePosixPath = css_dir, dropped: list[str] = dropped) -> str:
            if not (app / css_dir / match.group(1)).exists():
                dropped.append(match.group(0).strip())
                return ""
            return match.group(0)

        cleaned = _CSS_SOURCE.sub(drop_source, _CSS_IMPORT.sub(drop_import, text))
        if dropped:
            edits.append(CssEdit(relative, text, cleaned, tuple(dropped)))
    return edits


def _cleaned_package_json(app: Path, unavailable: list[str]) -> tuple[str, str]:
    raw = (app / "package.json").read_text(encoding="utf-8")
    package = json.loads(raw)
    for section in ("dependencies", "devDependencies"):
        for name in unavailable:
            package.get(section, {}).pop(name, None)
    if "workspaces" in package and not any(app.glob("packages/*/package.json")):
        package.pop("workspaces")
    return raw, json.dumps(package, indent=2, ensure_ascii=False) + "\n"


@dataclass
class CleanupAnalysis:
    """What portability cleanup WOULD do, computed without touching `app`
    (H2: the adaptation planner reads it from the read-only snapshot).
    `live_modules` = source modules reachable from the kept routes/entries."""

    unavailable_packages: list[str]
    blocking: list[str]
    removed_routes: list[str]
    removed_modules: list[str]
    live_modules: list[str]
    css_edits: list[CssEdit]
    package_json: tuple[str, str] | None  # (before, after)


def analyze_cleanup(app: Path) -> CleanupAnalysis:
    package = json.loads((app / "package.json").read_text(encoding="utf-8"))
    unavailable = _unavailable_workspace_packages(app, package)
    modules = _module_files(app)
    edges, direct = _graph(app, modules, unavailable)
    tainted = _tainted(edges, direct)
    blocking = [m for m in (*_PROTECTED_ROUTES, *_ENTRY_FILES) if m in tainted]
    routes = [m for m in modules if m.startswith("src/routes/")]
    removed_routes = [r for r in routes if r in tainted]
    roots = [r for r in routes if r not in tainted] + [e for e in _ENTRY_FILES if e in edges]
    kept = _reachable(edges, roots)
    if not unavailable:
        return CleanupAnalysis([], [], [], [], sorted(kept), [], None)
    return CleanupAnalysis(
        unavailable_packages=unavailable,
        blocking=blocking,
        removed_routes=removed_routes,
        removed_modules=sorted(m for m in tainted if m not in kept),
        live_modules=sorted(kept),
        css_edits=_css_edits(app, unavailable, modules, kept),
        package_json=_cleaned_package_json(app, unavailable),
    )


def portability_cleanup(app: Path) -> CleanupResult:
    """Applies the rule in the module docstring to the WORKING copy `app`."""
    analysis = analyze_cleanup(app)
    result = CleanupResult(unavailable_packages=analysis.unavailable_packages)
    if not analysis.unavailable_packages:
        return result
    if analysis.blocking:
        raise DesignCriticalDependencyError(
            "the public site needs unavailable package(s) "
            + ", ".join(analysis.unavailable_packages)
            + " via "
            + ", ".join(analysis.blocking)
        )
    result.removed_routes = analysis.removed_routes
    for module in analysis.removed_modules:
        why = "route" if module in analysis.removed_routes else "module"
        result.changes.append(
            remove_file(
                app,
                module,
                kind="cleanup-remove",
                reason=f"{why} depends on unavailable package(s) and is not reachable from the public site",
            )
        )
    for edit in analysis.css_edits:
        (app / edit.path).write_text(edit.after, encoding="utf-8")
        result.changes.append(
            ChangeRecord(
                edit.path,
                "cleanup-edit",
                "removed CSS references to unavailable packages/removed components: " + " | ".join(edit.dropped),
                None,
                sha256_hex(edit.before.encode()),
                sha256_hex(edit.after.encode()),
            )
        )
    assert analysis.package_json is not None
    before, after = analysis.package_json
    (app / "package.json").write_text(after, encoding="utf-8")
    result.changes.append(
        ChangeRecord(
            "package.json",
            "cleanup-edit",
            "removed unavailable workspace dependencies: " + ", ".join(analysis.unavailable_packages),
            None,
            sha256_hex(before.encode()),
            sha256_hex(after.encode()),
        )
    )
    return result
