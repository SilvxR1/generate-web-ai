"""`higgsfield-tanstack-static` (H2): the source-family adapter for
websites exported by Higgsfield Supercomputer as React + TanStack Start +
Vite projects built with bun, published by GWA as a prerendered static
artifact.

FAMILY knowledge only — everything below is derived from the
SourceManifest and the source's structure, never from one export's
names, copy or file layout:

- build: `bun install --ignore-scripts` (trusted), then the export's own
  `bun run build` in the R4 sandbox; recognised build steps; TanStack
  Start's documented `prerender` added to the `tanstackStart({...})`
  plugin options for every static page route + the legal routes;
- lead transport: a form that calls a TanStack server function with
  `fn({ data })` keeps its code; the import is pointed at a generated
  transport module with the same call shape (platform_files) and the
  server-only backend modules are removed;
- head: Google Fonts stylesheets -> self-hosted OFL @fontsource packages
  (only families GWA has verified), Fontshare kept (family CSP policy),
  canonical/og:url/JSON-LD in the index route's `head()`;
- Higgsfield page metadata (`src/app-meta.json`): builder-hosted image URLs
  removed, an owned og:image set;
- brand policy: an image rendered as the brand mark shows only an
  owner-approved logo (BusinessTruth);
- host hooks of the builder (its error-reporting global, its design
  inspector) are recognised as inert outside Higgsfield.

What the family cannot infer (where a design wants its legal links, how
to theme the consent banner, which frame is the share image, a
design-preserving fix) comes from a reviewed ExportOverlay or falls back
to neutral platform defaults.
"""

import json
import re
from io import BytesIO
from pathlib import PurePosixPath

from PIL import Image

from app.creative.source_adapter import platform_files as pf
from app.creative.source_adapter import tsx_scan as ts
from app.creative.source_adapter.adapters.base import (
    ADAPTER_CONTRACT_VERSION,
    BuildSpec,
    ExportOverlay,
    LegalPresentation,
    PlanContext,
)
from app.creative.source_adapter.classify import Finding
from app.creative.source_adapter.cleanup import analyze_cleanup
from app.creative.source_adapter.edits import edit_span, ensure_import, line_indent, relative_import
from app.creative.source_adapter.manifest import CODE_SUFFIXES, SourceManifest, is_server_only
from app.creative.source_adapter.plan import DELETE_KEY, PlanBuilder, PlanRefusedError, VirtualTree
from app.publishing.csp_policy import SourceFamily
from app.publishing.security_headers import CspExtensions

ADAPTER_ID = "higgsfield-tanstack-static"
VERSION = "1.0.0"

SDK_PATH = "src/lib/platform-sdk.ts"
PLATFORM_DIR = "src/platform"
LEGAL_ROUTES = (("privacy", "PrivacyPage"), ("terms", "TermsPage"), ("cookies", "CookiesPage"))
LEGAL_LOCALES = ("es", "en")
_BUILD_STEPS = (
    re.compile(r"vite build"),
    re.compile(r"tsc --noEmit"),
    re.compile(r"tsr generate"),
    re.compile(r"node scripts/[\w.-]+\.m?js"),
)
_SANDBOX_NODE_SCRIPT = re.compile(r"node (scripts/[\w.-]+\.m?js)")
_GOOGLE_FONT_ORIGINS = ("https://fonts.googleapis.com", "https://fonts.gstatic.com")
_OG_PATH = "public/og-image.jpg"
_INDEX_ROUTE = re.compile(r"createFileRoute\(\s*[\"']/[\"']\s*\)\(\s*\{")
_UNSAFE_VALUE = re.compile(r"[{}<>\"'`\\\n\r]")


def _finding(code: str, severity: str, subject: str, detail: str) -> Finding:
    return Finding(code, severity, subject, detail, "family")


def _resolve_in_tree(tree: VirtualTree, importer: str, spec: str) -> str | None:
    if spec.startswith("@/"):
        base = PurePosixPath("src") / spec[2:]
    elif spec.startswith("."):
        base = PurePosixPath(importer).parent / spec
    else:
        return None
    parts: list[str] = []
    for part in base.parts:
        if part == "..":
            if parts:
                parts.pop()
        elif part not in (".", ""):
            parts.append(part)
    stem = "/".join(parts)
    for candidate in (stem, *(f"{stem}{s}" for s in CODE_SUFFIXES), *(f"{stem}/index{s}" for s in CODE_SUFFIXES)):
        if tree.exists(candidate):
            return candidate
    return None


def _importers(tree: VirtualTree) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for path in tree.paths():
        if not path.startswith("src/") or not path.endswith(CODE_SUFFIXES):
            continue
        for decl in ts.imports(ts.scan(tree.text(path))):
            target = _resolve_in_tree(tree, path, decl.spec)
            if target is not None:
                graph.setdefault(target, set()).add(path)
    return graph


def _camel(family: str) -> str:
    words = [w for w in re.split(r"[^A-Za-z0-9]+", family) if w]
    return words[0].lower() + "".join(w.capitalize() for w in words[1:])


def _value_imports(clause: str | None) -> list[str]:
    """Names imported as values (not `type X`) by an import clause."""
    if not clause:
        return []
    named = re.search(r"\{([^}]*)\}", clause)
    names = []
    default = (clause[: named.start()] if named else clause).strip().rstrip(",").strip()
    if default and not default.startswith("type "):
        names.append(default)
    if named:
        for part in named.group(1).split(","):
            part = part.strip()
            if part and not part.startswith("type "):
                names.append(part.split(" as ")[-1].strip())
    return names


def _is_brand_image(s: ts.Scan, img: ts.JsxTag) -> bool:
    own = " ".join(filter(None, (ts.jsx_attr(img, "className"), ts.jsx_attr(img, "id"), ts.jsx_attr(img, "src"))))
    anchor = ts.enclosing_tag(s, img.start, "a")
    around = " ".join(filter(None, (ts.jsx_attr(anchor, "className"), ts.jsx_attr(anchor, "id")))) if anchor else ""
    return bool(re.search(r"logo|brand|mark", own, re.I) or re.search(r"brand|logo", around, re.I))


def default_og_source(manifest: SourceManifest, tree: VirtualTree) -> str | None:
    """Default share-image source: the largest landscape raster the export
    ships in public/ (>= 1200 px wide, aspect 1.3-2.4). Deterministic."""
    best: tuple[int, str] | None = None
    for image in manifest.images:
        path = image["path"]
        if not path.startswith("public/") or not path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            continue
        with Image.open(BytesIO(tree.read(path))) as picture:
            width, height = picture.size
        if width >= 1200 and 1.3 <= width / height <= 2.4:
            candidate = (-width * height, path)
            best = candidate if best is None or candidate < best else best
    return best[1] if best else None


class HiggsfieldTanstackAdapter:
    adapter_id = ADAPTER_ID
    version = VERSION
    contract_version = ADAPTER_CONTRACT_VERSION
    family = SourceFamily.HIGGSFIELD_TANSTACK.value

    @property
    def origin(self) -> str:
        return f"family:{self.adapter_id}@{self.version}"

    # --- detection / supportability ------------------------------------------------

    def detect(self, manifest: SourceManifest) -> bool:
        deps = manifest.framework["dependencies"]
        points = manifest.integration_points
        return (
            "@tanstack/react-start" in deps
            and "react" in deps
            and manifest.framework["router"] == "tanstack-file-routes"
            and bool(points["vite_config"])
            and bool(points["root_route"])
        )

    def lead_forms(self, manifest: SourceManifest) -> list[dict]:
        return [f for f in manifest.forms if f["live"] and "error" not in f]

    def server_removals(self, manifest: SourceManifest, tree: VirtualTree) -> list[str]:
        """Server-only backend modules a static artifact replaces: the server
        functions the lead forms call, dead server functions, and `.server`
        modules only those import."""
        live = set(manifest.modules["live"])
        removed: set[str] = set()
        for form in self.lead_forms(manifest):
            spec = form["transport"]["import_spec"]
            if form["transport"]["kind"] == "server-function" and spec:
                target = _resolve_in_tree(tree, form["module"], spec)
                if target:
                    removed.add(target)
        removed |= {p for p in manifest.integration_points["server_function_modules"] if p not in live}
        importers = _importers(tree)
        changed = True
        while changed:
            changed = False
            for module in manifest.integration_points["server_only_modules"]:
                users = importers.get(module, set())
                if module not in removed and users and users <= removed:
                    removed.add(module)
                    changed = True
        return sorted(p for p in removed if tree.exists(p))

    def assess(self, manifest: SourceManifest, tree: VirtualTree, overlay: ExportOverlay | None) -> list[Finding]:
        out: list[Finding] = []
        points = manifest.integration_points
        if manifest.package_manager["manager"] not in ("bun", None):
            out.append(
                _finding(
                    "package_manager_unsupported",
                    "blocker",
                    str(manifest.package_manager["lockfile"]),
                    "this family is installed and built with bun",
                )
            )
        steps = manifest.build["expanded"]
        if "vite build" not in steps:
            out.append(
                _finding("no_static_build", "blocker", "package.json", f"build steps {steps} never run vite build")
            )
        for step in steps:
            if not any(p.fullmatch(step) for p in _BUILD_STEPS):
                out.append(
                    _finding(
                        "build_step_unrecognized",
                        "review",
                        step,
                        "an unrecognised build step (it would run inside the no-network sandbox)",
                    )
                )
        for route in manifest.routes:
            if not route["live"]:
                continue
            if route["kind"] == "page" and route["dynamic"]:
                out.append(
                    _finding(
                        "dynamic_route_not_prerenderable",
                        "blocker",
                        str(route["path"]),
                        "a dynamic route cannot become a static page without a list of its pages",
                    )
                )
            if route["path"] in {f"/{slug}" for slug, _ in LEGAL_ROUTES}:
                out.append(
                    _finding(
                        "legal_route_conflict",
                        "blocker",
                        str(route["path"]),
                        "the export already defines a platform legal route",
                    )
                )
        vite = points["vite_config"]
        masked = ts.scan(tree.text(vite)).masked
        if len(re.findall(r"\btanstackStart\s*\(\s*\{", masked)) != 1:
            out.append(
                _finding(
                    "build_config_unrecognized",
                    "blocker",
                    vite,
                    "expected exactly one tanstackStart({...}) plugin call",
                )
            )
        if re.search(r"\bprerender\s*:", masked):
            out.append(
                _finding(
                    "prerender_already_configured",
                    "blocker",
                    vite,
                    "the export configures prerendering itself; merging is not supported",
                )
            )
        if not re.search(r"\bplugins\s*:", masked) or re.search(r"\bpreview\s*:", masked):
            out.append(
                _finding(
                    "build_config_unrecognized",
                    "blocker",
                    f"{vite}#preview",
                    "no Vite config object with `plugins`, or a `preview` option already set",
                )
            )
        if len(ts.jsx_open_tags(ts.scan(tree.text(points["root_route"])), "html")) != 1:
            out.append(
                _finding(
                    "root_document_unrecognized",
                    "blocker",
                    points["root_route"],
                    "the root route must render exactly one <html> element",
                )
            )
        index = points["index_route"]
        if index is None or not re.search(r"createFileRoute\(\s*[\"']/[\"']\s*\)\(\s*\{", tree.text(index)):
            out.append(_finding("index_route_unrecognized", "blocker", str(index), "no createFileRoute('/') route"))
        elif re.search(r"\bhead\s*:", ts.scan(tree.text(index)).masked):
            out.append(
                _finding(
                    "index_head_unsupported",
                    "blocker",
                    index,
                    "the index route defines head(); merging platform SEO into it is not supported",
                )
            )
        for font in manifest.fonts:
            if font["provider"] == "google-fonts" and font["family"] not in pf.SELF_HOSTED_FONTS:
                out.append(
                    _finding(
                        "font_not_self_hostable",
                        "blocker",
                        font["family"],
                        "Google Fonts cannot be allowed by the CSP and GWA has not verified a self-hosted "
                        "OFL package for this family",
                    )
                )
            if font["provider"] == "fontshare":
                out.append(
                    _finding(
                        "third_party_font_service",
                        "info",
                        font["family"],
                        "served by the Fontshare API (allowed by the family CSP policy; disclosed on /cookies)",
                    )
                )
        forms = self.lead_forms(manifest)
        if not forms:
            out.append(_finding("no_lead_form", "review", "site", "no live form: the site captures no leads"))
        for form in forms:
            transport = form["transport"]
            if transport["result_used"]:
                out.append(
                    _finding(
                        "form_displays_server_identifier",
                        "review",
                        form["form_id"],
                        "the form shows a value the builder's server returned (e.g. a record id); the GWA "
                        "Lead API returns none, and GWA never fabricates one",
                    )
                )
            if transport["kind"] == "server-function" and transport["symbol"]:
                decl = next(
                    (d for d in ts.imports(ts.scan(tree.text(form["module"]))) if d.spec == transport["import_spec"]),
                    None,
                )
                values = [n for n in _value_imports(decl.clause if decl else None) if n != transport["symbol"]]
                if values:
                    out.append(
                        _finding(
                            "form_transport_imports_more",
                            "blocker",
                            form["form_id"],
                            f"the form also imports {values} from its server module",
                        )
                    )
        removals = set(self.server_removals(manifest, tree))
        importers = _importers(tree)
        rewired = {f["module"] for f in forms}
        for module in sorted(removals):
            still = importers.get(module, set()) - removals - rewired
            if still:
                out.append(
                    _finding(
                        "server_module_still_imported",
                        "blocker",
                        module,
                        f"{sorted(still)} import a server module a static artifact cannot contain",
                    )
                )
        anchor = overlay.legal.links_anchor if overlay and overlay.legal else None
        footers = [f for f in points["footer_modules"] if f not in removals]
        if anchor is None and len(footers) != 1:
            out.append(
                _finding(
                    "legal_links_placement",
                    "review",
                    "footer",
                    f"{len(footers)} footer modules: where the legal links go needs a design decision",
                )
            )
        for brand in manifest.brand_assets:
            if brand["kind"] == "rendered-brand-image":
                out.append(
                    _finding(
                        "generated_brand_mark",
                        "info",
                        brand["path"],
                        "shown only if BusinessTruth has an owner-approved logo (brand policy)",
                    )
                )
        return out

    def resolve(self, finding: Finding, manifest: SourceManifest, tree: VirtualTree) -> str | None:
        code, subject = finding.code, finding.subject
        if code == "lifecycle_script":
            item = next((s for s in manifest.security if s["code"] == code and s.get("script") == subject), None)
            if item and subject == "postinstall" and _SANDBOX_NODE_SCRIPT.fullmatch(str(item.get("command"))):
                return (
                    "never run by the install (bun install --ignore-scripts); run only as a build step inside the "
                    "no-network R4 sandbox"
                )
        if code == "server_runtime" and subject in self.server_removals(manifest, tree):
            return "server module removed: the lead backend is replaced by the GWA public Lead API (static artifact)"
        if code == "host_hook":
            hook, _, path = subject.partition("@")
            if hook == "higgsfield-error-reporting":
                return "calls window.__higgsfieldEvents, a global only the Higgsfield host injects: inert (no network)"
            vite = tree.text(manifest.integration_points["vite_config"])
            if (
                hook == "cross-window-message"
                and path.startswith("src/module/design-inspector/")
                and ("HF_DESIGN_INSPECTOR" in vite)
            ):
                return "Higgsfield design inspector: compiled out unless HF_DESIGN_INSPECTOR is set (never by GWA)"
        if code == "network_origin_not_permitted":
            origin = subject.split(" ", 1)[0]
            entries = [o for o in manifest.external_origins if o["origin"] == origin and o["live"]]
            google = [f for f in manifest.fonts if f["provider"] == "google-fonts"]
            if origin in _GOOGLE_FONT_ORIGINS and google and all(f["family"] in pf.SELF_HOSTED_FONTS for f in google):
                return "Google Fonts replaced by self-hosted OFL @fontsource packages (no request to Google)"
            meta = manifest.metadata.get("app_meta_file")
            if meta and entries and all(set(e["files"]) <= {meta} for e in entries):
                return "builder-hosted page-metadata image removed (asset policy); an owned og:image is derived"
        return None

    def csp_requirements(self, manifest: SourceManifest, tree: VirtualTree) -> CspExtensions:
        live = [p for p in manifest.modules["live"] if tree.exists(p)]
        blob_video = bool(manifest.videos) and any("URL.createObjectURL" in tree.text(p) for p in live)
        fontshare = any(f["provider"] == "fontshare" for f in manifest.fonts)
        return CspExtensions(
            media_blob=blob_video,
            style_origins=("https://api.fontshare.com",) if fontshare else (),
            font_origins=("https://cdn.fontshare.com",) if fontshare else (),
        )

    def locale(self, manifest: SourceManifest, tree: VirtualTree) -> str:
        tags = ts.jsx_open_tags(ts.scan(tree.text(manifest.integration_points["root_route"])), "html")
        lang = (ts.jsx_attr(tags[0], "lang") or "en").split("-")[0].lower() if tags else "en"
        return lang if lang in LEGAL_LOCALES else "en"

    def text_paths(self, manifest: SourceManifest, tree: VirtualTree) -> list[str]:
        removed = set(self.server_removals(manifest, tree))
        paths = [p for p in manifest.modules["live"] if p not in removed and not is_server_only(p)]
        meta = manifest.metadata.get("app_meta_file")
        return sorted(paths + ([meta] if meta else []))

    def build_spec(self, manifest: SourceManifest, pages: tuple[str, ...]) -> BuildSpec:
        steps: list[tuple[str, tuple[str, ...]]] = []
        post = next(
            (s for s in manifest.security if s["code"] == "lifecycle_script" and s.get("script") == "postinstall"), None
        )
        match = _SANDBOX_NODE_SCRIPT.fullmatch(str(post["command"])) if post else None
        if match:
            steps.append(("postinstall check", ("node", match.group(1))))
        steps.append(("bun run build", ("bun", "run", "build")))
        html = tuple(sorted("index.html" if p == "/" else f"{p.strip('/')}/index.html" for p in pages))
        return BuildSpec("bun", ("bun", "install", "--ignore-scripts"), tuple(steps), "dist/client", html)

    # --- planning ------------------------------------------------------------------

    def plan(self, context: PlanContext, builder: PlanBuilder) -> tuple[str, ...]:
        m, tree, overlay = context.manifest, context.tree, context.overlay
        self._bind_facts(context, builder)
        self._cleanup(context, builder)
        if overlay is not None:
            for patch in overlay.patches:
                note = f" [resolves {', '.join(patch.resolves)}]" if patch.resolves else ""
                builder.replace(
                    patch.path,
                    patch.find,
                    patch.replace,
                    category=patch.category,
                    reason=patch.reason + note,
                    visible=patch.visible,
                    origin=f"overlay:{overlay.name}",
                )
        removals = self.server_removals(m, tree)
        self._lead_transport(context, builder)
        for module in removals:
            if builder.tree.exists(module):
                builder.remove(
                    module,
                    category="lead-transport",
                    reason="server-only backend replaced by the GWA public Lead API (static artifact)",
                )
        root = m.integration_points["root_route"]
        builder.add(
            SDK_PATH,
            pf.platform_sdk(),
            category="platform-sdk",
            reason="GWA Platform SDK, verbatim (consent-gated analytics, window.gwaConsent, lead transport)",
        )
        ensure_import(
            builder,
            root,
            f'import "{relative_import(root, SDK_PATH)}";',
            category="platform-sdk",
            reason="load the Platform SDK on every page",
        )
        if overlay is not None and overlay.consent_theme:
            self._consent_theme(context, builder, overlay.consent_theme)
        self._fonts(context, builder)
        self._legal(context, builder, removals)
        self._seo(context, builder)
        self._brand(context, builder)
        static_pages = sorted(
            r["path"]
            for r in m.routes
            if r["live"] and r["kind"] == "page" and not r["dynamic"] and r["path"] not in (None, "/")
        )
        pages = ("/", *static_pages, *(f"/{slug}" for slug, _ in LEGAL_ROUTES))
        self._build_config(context, builder, pages)
        return pages

    def _bind_facts(self, context: PlanContext, builder: PlanBuilder) -> None:
        """BusinessTruth values replace the export's literals, on the pristine
        text (offsets from discovery), last occurrence first per file."""
        edits: dict[str, list[tuple[int, int, str, str]]] = {}
        for binding in context.facts.bindings:
            if binding.literal == binding.value:
                continue
            for o in binding.occurrences:
                edits.setdefault(o.path, []).append((o.start, o.end, binding.value, binding.field))
        for path, spans in sorted(edits.items()):
            for start, end, value, field_name in sorted(spans, reverse=True):
                if _UNSAFE_VALUE.search(value) or not value.strip():
                    raise PlanRefusedError(f"{field_name}: value cannot be bound safely into {path}")
                literal = builder.tree.text(path)[start:end]
                edit_span(
                    builder,
                    path,
                    start,
                    end,
                    value,
                    category="business-truth",
                    reason=f"BusinessTruth {field_name} = {value!r}",
                    visible=f"{literal!r} -> {value!r}",
                )

    def _cleanup(self, context: PlanContext, builder: PlanBuilder) -> None:
        analysis = analyze_cleanup(context.snapshot_app)
        if analysis.blocking:
            raise PlanRefusedError(f"design-critical unavailable packages via {analysis.blocking}")
        for module in analysis.removed_modules:
            why = "route" if module in analysis.removed_routes else "module"
            builder.remove(
                module,
                category="cleanup",
                reason=f"{why} depends on unavailable builder package(s) "
                f"{analysis.unavailable_packages} and is not reachable from the public site",
            )
        for edit in analysis.css_edits:
            builder.replace(
                edit.path,
                edit.before,
                edit.after,
                category="cleanup",
                reason="removed CSS references to unavailable packages/removed components: " + " | ".join(edit.dropped),
            )
        if analysis.package_json is not None:
            before, after = (json.loads(t) for t in analysis.package_json)
            changes: dict[str, object] = {k: after[k] for k in after if before.get(k) != after[k]}
            changes |= {k: DELETE_KEY for k in before if k not in after}
            builder.json(
                "package.json",
                changes,
                category="cleanup",
                reason=f"removed unavailable workspace dependencies {analysis.unavailable_packages}",
            )

    def _lead_transport(self, context: PlanContext, builder: PlanBuilder) -> None:
        by_id = {f["form_id"]: f for f in self.lead_forms(context.manifest)}
        for i, mapping in enumerate(context.form_mappings):
            form = by_id[mapping.form_id]
            transport = form["transport"]
            module = mapping.module
            key = f"lead-{i + 1}"
            shim = f"{PLATFORM_DIR}/lead-transport{'' if i == 0 else f'-{i + 1}'}.ts"
            decl = next(d for d in ts.imports(ts.scan(builder.tree.text(module))) if d.spec == transport["import_spec"])
            types = [n for n in ts.imported_names(decl.clause) if n != transport["symbol"]]
            builder.add(
                shim,
                pf.lead_transport_ts(
                    mapping,
                    symbol=transport["symbol"],
                    type_names=types,
                    form_key=key,
                    sdk_module=relative_import(shim, SDK_PATH),
                ),
                category="lead-transport",
                reason=f"{mapping.form_id}: the form's server function -> GWA Lead API, same call shape; every field "
                "sent (core fields + labelled details), submission id reused across retries",
            )
            quoted = re.search(r"([\"'])" + re.escape(transport["import_spec"]) + r"\1", decl.statement)
            if quoted is None:
                raise PlanRefusedError(f"{module}: cannot locate the server-function import")
            new_statement = decl.statement.replace(quoted.group(0), f'"{relative_import(module, shim)}"', 1)
            builder.replace(
                module,
                decl.statement,
                new_statement,
                category="lead-transport",
                reason=f"{mapping.form_id}: import the platform transport instead of the builder's server function",
            )
            text = builder.tree.text(module)
            tag = ts.jsx_open_tags(ts.scan(text), "form")[form["index"]]
            opened = f'<form data-gwa-lead-form="{key}"' + text[tag.start + len("<form") : tag.end]
            honeypot = pf.honeypot_jsx(context.site.locale, line_indent(text, tag.start) + "  ").rstrip("\n")
            edit_span(
                builder,
                module,
                tag.start,
                tag.end,
                f"{opened}\n{honeypot}",
                category="lead-transport",
                reason=f"{mapping.form_id}: PlatformContract lead-form hook + Lead API honeypot (off-screen)",
            )

    def _consent_theme(self, context: PlanContext, builder: PlanBuilder, theme: dict[str, str]) -> None:
        root = context.manifest.integration_points["root_route"]
        path = f"{PLATFORM_DIR}/consent-theme.ts"
        builder.add(
            path,
            pf.consent_theme_ts(theme),
            category="consent",
            reason="consent banner themed with the site's own tokens (--gwa-consent-* only)",
        )
        ensure_import(
            builder,
            root,
            f'import {{ GWA_CONSENT_THEME }} from "{relative_import(root, path)}";',
            category="consent",
            reason="consent theme",
        )
        text = builder.tree.text(root)
        tag = ts.jsx_open_tags(ts.scan(text), "html")[0]
        tag_text = text[tag.start : tag.end]
        style = re.search(r"\bstyle\s*=\s*\{", tag_text)
        if style is None:
            new_tag = tag_text[:-1].rstrip() + " style={GWA_CONSENT_THEME}>"
        else:
            brace = style.end() - 1
            if tag_text[brace + 1] != "{":
                raise PlanRefusedError("the <html> style is not an object literal; theming it needs review")
            obj_close = ts.matching(ts.scan(tag_text), brace + 1)
            obj = tag_text[brace + 1 : obj_close + 1]
            new_obj = obj[:-1].rstrip().rstrip(",") + ", ...GWA_CONSENT_THEME }"
            new_tag = tag_text[: brace + 1] + new_obj + tag_text[obj_close + 1 :]
        edit_span(
            builder,
            root,
            tag.start,
            tag.end,
            new_tag,
            category="consent",
            reason="theme the platform consent banner through its documented variables only",
        )

    def _fonts(self, context: PlanContext, builder: PlanBuilder) -> None:
        google = sorted(
            (f for f in context.manifest.fonts if f["provider"] == "google-fonts"), key=lambda f: f["family"]
        )
        if not google:
            return
        root = context.manifest.integration_points["root_route"]
        variables: list[tuple[str, str]] = []
        added: dict[str, str] = {}
        for font in google:
            package, version = pf.SELF_HOSTED_FONTS[font["family"]]
            added[package] = version
            variables += [(f"{_camel(font['family'])}{w}", f"{package}/{w}.css?url") for w in font["weights"]]
        s = ts.scan(builder.tree.text(root))
        spans: set[tuple[int, int, bool]] = set()  # (start, end, is_stylesheet)
        for token in s.strings:
            if not token.value.startswith(_GOOGLE_FONT_ORIGINS):
                continue
            obj = ts.enclosing(s, token.start, "{")
            if obj is None or ts.enclosing(s, obj, "[") is None:
                raise PlanRefusedError("a Google Fonts link is not an element of a head links array")
            spans.add((obj, ts.matching(s, obj) + 1, "/css" in token.value))
        if sum(1 for *_, sheet in spans if sheet) != 1:
            raise PlanRefusedError("expected exactly one Google Fonts stylesheet link in the root head")
        for start, end, sheet in sorted(spans, reverse=True):
            text = builder.tree.text(root)
            if sheet:
                links = f",\n{line_indent(text, start)}".join(
                    f'{{ rel: "stylesheet", href: {v} }}' for v, _ in variables
                )
                edit_span(
                    builder,
                    root,
                    start,
                    end,
                    links,
                    category="fonts",
                    reason="Google Fonts stylesheet -> the same families and weights, self-hosted (OFL @fontsource)",
                )
            else:
                after = re.match(r"\s*,[ \t]*\n[ \t]*", text[end:])
                edit_span(
                    builder,
                    root,
                    start,
                    end + (after.end() if after else 0),
                    "",
                    category="fonts",
                    reason="preconnect to Google Fonts no longer needed (self-hosted)",
                )
        for variable, module in variables:
            ensure_import(
                builder,
                root,
                f'import {variable} from "{module}";',
                category="fonts",
                reason="self-hosted OFL font stylesheet (emitted as a same-origin asset)",
            )
        deps = dict(json.loads(builder.tree.text("package.json")).get("dependencies", {}))
        clash = sorted(set(added) & set(deps))
        if clash:
            raise PlanRefusedError(f"{clash} already declared by the export")
        builder.json(
            "package.json",
            {"dependencies": dict(sorted({**deps, **added}.items()))},
            category="fonts",
            reason="platform font packages: " + ", ".join(f"{p}@{v}" for p, v in sorted(added.items())),
        )

    def _legal(self, context: PlanContext, builder: PlanBuilder, removals: list[str]) -> None:
        m, overlay, locale = context.manifest, context.overlay, context.site.locale
        presentation = overlay.legal if overlay and overlay.legal else LegalPresentation()
        fontshare = any(f["provider"] == "fontshare" for f in m.fonts)
        third = (pf.THIRD_PARTY_DISCLOSURES["fontshare"][locale],) if fontshare else ()
        builder.add(
            f"{PLATFORM_DIR}/legal-content.json",
            pf.legal_content_json(context.truth, locale, third),
            category="legal",
            reason="legal wording rendered from BusinessTruth (owner/legal review needed)",
        )
        links = f"{PLATFORM_DIR}/legal-links.tsx"
        builder.add(
            links,
            pf.legal_links_tsx(locale, presentation.nav_class, presentation.link_class),
            category="legal",
            reason="legal navigation + cookie preferences",
            visible="legal links (privacy, legal notice, cookies, cookie preferences)",
        )
        page = f"{PLATFORM_DIR}/legal-page.tsx"
        kind = "reviewed presentation in the site's classes" if presentation.page_tsx else "neutral platform default"
        builder.add(
            page,
            presentation.page_tsx or pf.default_legal_page_tsx(locale),
            category="legal",
            reason=f"legal page layout ({kind})",
            visible="new pages /privacy, /terms, /cookies",
        )
        for slug, component in LEGAL_ROUTES:
            route = f"src/routes/{slug}.tsx"
            builder.add(
                route,
                pf.legal_route_tsx(slug, component, relative_import(route, page)),
                category="legal",
                reason=f"legal route /{slug}",
            )
        if presentation.links_anchor is not None:
            module, fragment = presentation.links_anchor
            indent = fragment[: len(fragment) - len(fragment.lstrip())]
            builder.replace(
                module,
                fragment,
                f"{indent}<LegalLinks />\n{fragment}",
                category="legal",
                reason="legal links where the reviewed presentation places them",
                visible="footer gains legal links",
            )
        else:
            footers = [f for f in m.integration_points["footer_modules"] if f not in removals]
            if len(footers) != 1:
                raise PlanRefusedError("no single footer for the legal links and no reviewed placement")
            module = footers[0]
            text = builder.tree.text(module)
            s = ts.scan(text)
            close, _ = ts.jsx_close_tag(s, ts.jsx_open_tags(s, "footer")[0])
            line_start = text.rfind("\n", 0, close) + 1
            if text[line_start:close].strip():
                raise PlanRefusedError(f"{module}: </footer> does not start its line; placement needs review")
            edit_span(
                builder,
                module,
                line_start,
                line_start,
                f"{line_indent(text, close)}  <LegalLinks />\n",
                category="legal",
                reason="legal links appended to the site footer",
                visible="footer gains legal links",
            )
        ensure_import(
            builder,
            module,
            f'import {{ LegalLinks }} from "{relative_import(module, links)}";',
            category="legal",
            reason="legal links component",
        )

    def _seo(self, context: PlanContext, builder: PlanBuilder) -> None:
        m, site, overlay = context.manifest, context.site, context.overlay
        business = f"{PLATFORM_DIR}/business.ts"
        builder.add(
            business,
            pf.business_module(context.truth, site.origin),
            category="seo",
            reason="business facts + truth-only JSON-LD from BusinessTruth",
        )
        index = m.integration_points["index_route"]
        text = builder.tree.text(index)
        scanned = ts.scan(text)
        call = next((c for c in _INDEX_ROUTE.finditer(text) if scanned.is_code(c.start())), None)
        if call is None:
            raise PlanRefusedError(f"{index}: no createFileRoute('/') route")
        brace = call.end()
        next_line = text[text.find("\n", brace) + 1 :]
        indent = next_line[: len(next_line) - len(next_line.lstrip(" \t"))] or "  "
        head = (
            f"\n{indent}// GWA platform: canonical URL, og:url and structured data (BusinessTruth only).\n"
            f"{indent}head: () => ({{\n"
            f'{indent}  links: [{{ rel: "canonical", href: `${{BUSINESS.siteOrigin}}/` }}],\n'
            f'{indent}  meta: [{{ property: "og:url", content: `${{BUSINESS.siteOrigin}}/` }}],\n'
            f'{indent}  scripts: [{{ type: "application/ld+json", children: SITE_JSONLD }}],\n'
            f"{indent}}}),"
        )
        edit_span(builder, index, brace, brace, head, category="seo", reason="canonical URL, og:url and JSON-LD")
        ensure_import(
            builder,
            index,
            f'import {{ BUSINESS, SITE_JSONLD }} from "{relative_import(index, business)}";',
            category="seo",
            reason="SEO data module",
        )
        source = (overlay.og_image_source if overlay else None) or default_og_source(m, builder.tree)
        og_url = None
        if source is not None:
            if builder.tree.exists(_OG_PATH):
                raise PlanRefusedError(f"{_OG_PATH} already exists in the export")
            builder.add(
                _OG_PATH,
                pf.derive_og_image(builder.tree.read(source)),
                category="assets",
                reason=f"owned Open Graph image: {source} center-cropped to 1200x630 (no builder CDN)",
                visible="link previews show the site's own frame",
            )
            og_url = f"{site.origin}/og-image.jpg"
        meta = m.metadata.get("app_meta_file")
        if meta:
            values: dict[str, object] = {e["key"]: None for e in m.metadata["app_meta_external"]}
            expect: dict[str, object] = {e["key"]: f"prefix:{e['origin']}/" for e in m.metadata["app_meta_external"]}
            if og_url is not None:
                values["og_image_url"] = og_url
            if values:
                builder.json(
                    meta,
                    values,
                    expect=expect,
                    category="assets",
                    reason="page metadata: builder-hosted images removed; og:image = the owned image on the "
                    "canonical origin",
                )

    def _brand(self, context: PlanContext, builder: PlanBuilder) -> None:
        modules = sorted(
            {
                ref
                for b in context.manifest.brand_assets
                if b["kind"] == "rendered-brand-image"
                for ref in b["referenced_by"]
            }
        )
        business = f"{PLATFORM_DIR}/business.ts"
        for module in modules:
            s = ts.scan(builder.tree.text(module))
            images = [img for img in ts.jsx_open_tags(s, "img") if _is_brand_image(s, img)]
            for img in sorted(images, key=lambda t: t.start, reverse=True):
                text = builder.tree.text(module)
                tag = text[img.start : img.end]
                src = re.search(r"\bsrc\s*=\s*(\"[^\"]*\"|'[^']*'|\{[^}]*\})", tag)
                if src is None:
                    raise PlanRefusedError(f"{module}: a brand image without a src")
                indent = line_indent(text, img.start)
                inner = tag.replace(src.group(0), "src={BUSINESS.logo.src}", 1).replace("\n", "\n  ")
                wrapped = (
                    "{/* GWA brand policy: only an owner-approved logo (BusinessTruth) is shown here. */}\n"
                    f"{indent}{{BUSINESS.logo ? (\n{indent}  {inner}\n{indent}) : null}}"
                )
                edit_span(
                    builder,
                    module,
                    img.start,
                    img.end,
                    wrapped,
                    category="brand",
                    reason="a builder-generated brand mark is not an owner-approved logo (TruthContract)",
                    visible="brand mark shown only for an owner-approved logo",
                )
            ensure_import(
                builder,
                module,
                f'import {{ BUSINESS }} from "{relative_import(module, business)}";',
                category="brand",
                reason="logo from BusinessTruth",
            )

    def _build_config(self, context: PlanContext, builder: PlanBuilder, pages: tuple[str, ...]) -> None:
        vite = context.manifest.integration_points["vite_config"]
        text = builder.tree.text(vite)
        s = ts.scan(text)
        call = re.search(r"\btanstackStart\s*\(\s*\{", s.masked)
        if call is None:
            raise PlanRefusedError(f"{vite}: no tanstackStart({{...}}) call")
        open_brace = call.end() - 1
        close = ts.matching(s, open_brace)
        body = text[open_brace + 1 : close]
        head, tail = body.rstrip(), body[len(body.rstrip()) :]
        indent = line_indent(text, close) + "  "
        comma = "" if not head.strip() or head.endswith(",") else ","
        page_list = ", ".join(f'{{ path: "{p}" }}' for p in pages)
        added = (
            f"{comma}\n{indent}// GWA adapter: prerender every public page to static HTML (TanStack Start's\n"
            f"{indent}// documented prerender) — the artifact needs no server.\n"
            f"{indent}prerender: {{ enabled: true, crawlLinks: false, autoSubfolderIndex: true, failOnError: true }},\n"
            f"{indent}pages: [{page_list}],"
        )
        edit_span(
            builder,
            vite,
            open_brace + 1,
            close,
            head + added + tail,
            category="build",
            reason=f"static artifact: prerender {list(pages)}",
        )
        text = builder.tree.text(vite)
        s = ts.scan(text)
        plugins = re.search(r"\bplugins\s*:", s.masked)
        config = ts.enclosing(s, plugins.start(), "{") if plugins else None
        if config is None:
            raise PlanRefusedError(f"{vite}: no Vite config object with plugins")
        next_line = text[text.find("\n", config) + 1 :]
        pad = next_line[: len(next_line) - len(next_line.lstrip(" \t"))]
        preview = (
            f"\n{pad}// GWA adapter: the prerender preview server binds an IP literal — the R4\n"
            f"{pad}// build sandbox has no name resolution at all.\n"
            f'{pad}preview: {{ host: "127.0.0.1" }},'
        )
        edit_span(
            builder,
            vite,
            config + 1,
            config + 1,
            preview,
            category="build",
            reason="prerender inside the no-network sandbox: no hostname resolution needed",
        )


ADAPTER = HiggsfieldTanstackAdapter()
