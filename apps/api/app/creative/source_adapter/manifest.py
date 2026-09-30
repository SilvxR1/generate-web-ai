"""SourceManifest (H2): a deterministic, STATIC inspection of an exported
website source, taken from the immutable snapshot before anything is
modified.

Nothing in the source is executed, installed or built to inspect it: the
manifest is computed from file bytes (package.json, lockfile, the import
graph, tsx_scan of modules, CSS text, magic bytes). Identical snapshot
bytes always produce the identical manifest (no timestamps, no absolute
paths, every list sorted) and its SHA-256 is the manifest's identity; it
carries the snapshot's ZIP SHA-256, so it is bound to the source it
describes. External URLs are recorded by ORIGIN only (a builder CDN path
can carry an account id).

What it records (see SourceManifest): framework and build system,
dependencies, lifecycle scripts, routes, forms, navigation, media, fonts,
brand assets, external origins (with the context each is used in),
analytics and tracking, host hooks, metadata/SEO, structured data,
factual-claim candidates, platform integration points and security
observations (secret-like strings, binaries, remote scripts, dynamic code,
server runtime).

LIVE vs dead: exports ship builder kits and demo routes the public site
never loads. `live` = reachable from the kept routes/entries (the
portability-cleanup import graph); most findings only matter when live.

This is inspection, not a security audit or a malware scanner: patterns
catch the obvious cases and report them; they do not prove absence.
"""

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from app.creative.source_adapter import tsx_scan as ts
from app.creative.source_adapter.cleanup import analyze_cleanup
from app.creative.source_adapter.facts import detect_claims
from app.creative.source_adapter.forms import discover_forms
from app.creative.source_adapter.plan import canonical_json, sha256_hex

MANIFEST_VERSION = "1.0.0"

CODE_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
TEXT_SUFFIXES = (
    *CODE_SUFFIXES,
    ".css",
    ".json",
    ".jsonc",
    ".html",
    ".md",
    ".toml",
    ".yaml",
    ".yml",
    ".sql",
    ".txt",
    ".svg",
    ".webmanifest",
    ".xml",
    ".env",
    ".sh",
)
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif", ".svg", ".ico")
VIDEO_SUFFIXES = (".mp4", ".webm", ".mov", ".m4v", ".ogv")
FONT_SUFFIXES = (".woff", ".woff2", ".ttf", ".otf")
LIFECYCLE_SCRIPTS = ("preinstall", "install", "postinstall", "prepare", "preprepare", "postprepare", "prepublish")
LOCKFILES = {
    "bun.lock": "bun",
    "bun.lockb": "bun",
    "package-lock.json": "npm",
    "pnpm-lock.yaml": "pnpm",
    "yarn.lock": "yarn",
}
FRAMEWORK_PACKAGES = (
    "react",
    "react-dom",
    "@tanstack/react-start",
    "@tanstack/react-router",
    "vite",
    "tailwindcss",
    "astro",
    "next",
    "nuxt",
    "@sveltejs/kit",
    "vue",
    "svelte",
    "@remix-run/react",
    "gatsby",
)

_URL = re.compile(r"(?:https?:)?//([a-z0-9-]+(?:\.[a-z0-9-]+)+)(?::\d+)?(/[^\s\"'`)<>]*)?", re.I)
_IGNORED_HOSTS = frozenset({"www.w3.org", "www.sitemaps.org", "schema.org", "json-schema.org", "example.com"})
_SECRET_PATTERNS = {
    "aws-access-key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----"),
    "anthropic-or-openai-key": re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{24,}"),
    "github-token": re.compile(r"\b(?:ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{40,})"),
    "slack-token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    "stripe-secret": re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}"),
    "google-api-key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "assigned-secret": re.compile(
        r"(?i)\b(?:api[_-]?key|secret|token|password|passwd|auth[_-]?key)\b\s*[:=]\s*[\"'][A-Za-z0-9/+_=.-]{16,}[\"']"
    ),
}
_BINARY_MAGIC = {
    b"\x7fELF": "elf",
    b"MZ": "pe",
    b"\xfe\xed\xfa\xce": "mach-o",
    b"\xfe\xed\xfa\xcf": "mach-o",
    b"\xcf\xfa\xed\xfe": "mach-o",
    b"\xca\xfe\xba\xbe": "mach-o",
    b"\x00asm": "wasm",
}
_BINARY_SUFFIXES = (".exe", ".dll", ".so", ".dylib", ".node", ".wasm", ".bin", ".jar", ".class")
_ANALYTICS = {
    "google-analytics": re.compile(
        r"googletagmanager\.com|google-analytics\.com|\bgtag\s*(?:\?\.)?\(|\bdataLayer\.push"
    ),
    "meta-pixel": re.compile(r"connect\.facebook\.net|\bfbq\s*(?:\?\.)?\("),
    "plausible": re.compile(r"plausible\.io"),
    "posthog": re.compile(r"posthog"),
    "segment": re.compile(r"cdn\.segment\.com|analytics\.load\("),
    "hotjar": re.compile(r"hotjar"),
    "microsoft-clarity": re.compile(r"clarity\.ms"),
    "mixpanel": re.compile(r"mixpanel"),
    "amplitude": re.compile(r"amplitude"),
    "sentry": re.compile(r"@sentry/|sentry\.io"),
    "cloudflare-insights": re.compile(r"cloudflareinsights\.com"),
    "vercel-analytics": re.compile(r"@vercel/analytics"),
    "tiktok-pixel": re.compile(r"analytics\.tiktok\.com"),
    "linkedin-insight": re.compile(r"snap\.licdn\.com"),
    "beacon": re.compile(r"navigator\.sendBeacon\("),
}
_HOST_HOOKS = {
    "higgsfield-error-reporting": re.compile(r"window\.__higgsfieldEvents"),
    "cross-window-message": re.compile(r"window\.parent\.postMessage\("),
}
_PLATFORM_MARKERS = ("data-gwa-lead-form", "lib/platform-sdk", "gwa-consent", "platform/business")


@dataclass
class SourceManifest:
    manifest_version: str
    snapshot: dict[str, Any]
    framework: dict[str, Any]
    package_manager: dict[str, Any]
    build: dict[str, Any]
    dependencies: list[dict[str, str]]
    modules: dict[str, Any]
    routes: list[dict[str, Any]]
    forms: list[dict[str, Any]]
    navigation: list[dict[str, Any]]
    images: list[dict[str, Any]]
    videos: list[dict[str, Any]]
    fonts: list[dict[str, Any]]
    brand_assets: list[dict[str, Any]]
    external_origins: list[dict[str, Any]]
    analytics: list[dict[str, Any]]
    host_hooks: list[dict[str, Any]]
    metadata: dict[str, Any]
    structured_data: list[dict[str, Any]]
    claims: list[dict[str, Any]]
    integration_points: dict[str, Any]
    security: list[dict[str, Any]]
    already_adapted: list[str] = field(default_factory=list)

    @property
    def sha256(self) -> str:
        return sha256_hex(canonical_json(asdict(self)))

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "manifest_sha256": self.sha256}

    def summary(self) -> dict[str, Any]:
        return {
            "manifest_sha256": self.sha256,
            "framework": self.framework,
            "package_manager": self.package_manager["manager"],
            "build_command": self.build["command"],
            "files": self.snapshot["files"],
            "live_modules": len(self.modules["live"]),
            "routes": [r["path"] or r["file"] for r in self.routes if r["live"]],
            "forms": [f["form_id"] for f in self.forms if f["live"]],
            "images": len(self.images),
            "videos": len(self.videos),
            "fonts": sorted({f"{f['family']} ({f['provider']})" for f in self.fonts}),
            "external_origins_client": sorted({o["origin"] for o in self.external_origins if o["live"]}),
            "analytics": sorted({a["vendor"] for a in self.analytics if a["live"]}),
            "security": sorted({s["code"] for s in self.security}),
            "claims": len(self.claims),
        }


def _code_only(text: str) -> str:
    """Comments and literal contents masked (a word in a comment is not code)."""
    try:
        return ts.scan(text).masked
    except ts.ScanError:
        return text


def _read_text(app: Path, rel: str) -> str:
    return (app / rel).read_text(encoding="utf-8", errors="replace")


def _files(app: Path) -> list[str]:
    return sorted(
        rel
        for rel in (p.relative_to(app).as_posix() for p in app.rglob("*") if p.is_file())
        if not rel.startswith(("node_modules/", "dist/"))
    )


def _dependency_kind(spec: str) -> str:
    if spec.startswith("workspace:"):
        return "workspace"
    if spec.startswith(("git", "github:")) or spec.endswith(".git"):
        return "git"
    if spec.startswith(("http:", "https:")):
        return "url"
    if spec.startswith(("file:", "link:", "portal:")):
        return "file"
    if spec.startswith("npm:"):
        return "alias"
    return "registry"


def build_commands(scripts: dict[str, str], name: str, seen: frozenset[str] = frozenset()) -> list[str]:
    """The flattened command list `bun run <name>` executes (scripts expanded)."""
    command = scripts.get(name)
    if command is None or name in seen:
        return [f"<unresolved script {name}>"]
    out: list[str] = []
    for part in (p.strip() for p in command.split("&&")):
        m = re.fullmatch(r"(?:bun|npm|pnpm|yarn)\s+run\s+([\w:.-]+)", part)
        out += build_commands(scripts, m.group(1), seen | {name}) if m else [part]
    return out


def json_loose(text: str) -> dict[str, Any]:
    """JSON with // and /* */ comments and trailing commas (tsconfig/jsonc)."""
    masked = ts.scan(text).masked
    stripped = "".join(" " if masked[i] == " " and ch not in " \t\r\n" else ch for i, ch in enumerate(text))
    stripped = re.sub(r",(\s*[}\]])", r"\1", stripped)
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def resolve_spec(app: Path, importer: str, spec: str) -> str | None:
    """`@/x` / relative import -> the module file it names (None if external)."""
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
        if (app / candidate).is_file():
            return candidate
    return None


def is_server_only(rel: str) -> bool:
    return bool(re.search(r"\.server\.[tj]sx?$|^src/server\.[tj]sx?$", rel))


def is_client_live(rel: str, live: set[str]) -> bool:
    """Reaches the visitor's browser: a live, non-server module or stylesheet,
    a page-metadata file, or a public asset — never tooling config or tests."""
    if rel.endswith(CODE_SUFFIXES) or rel.endswith(".css"):
        return rel in live and not is_server_only(rel)
    return rel.startswith(("public/", "src/")) or rel == "index.html"


def _routes(app: Path, files: list[str], removed: set[str]) -> list[dict[str, Any]]:
    routes = []
    for module in files:
        if not module.startswith("src/routes/") or not module.endswith(CODE_SUFFIXES):
            continue
        text = _read_text(app, module)
        page = re.search(r"createFileRoute\(\s*[\"']([^\"']+)[\"']\s*\)", text)
        root = re.search(r"createRootRoute(?:WithContext)?\b", text)
        server = re.search(r"\bserver\s*:\s*\{\s*handlers\b|createServerFileRoute|createAPIFileRoute", text)
        path = page.group(1) if page else None
        kind = "root" if root else "server" if server and not re.search(r"\bcomponent\s*:", text) else "page"
        routes.append(
            {
                "file": module,
                "path": path,
                "kind": kind,
                "dynamic": bool(path and "$" in path),
                "live": module not in removed,
                "has_head": bool(re.search(r"\bhead\s*:", text)),
            }
        )
    return routes


def _url_context(before: str) -> str:
    w = before.lower()[-160:]
    if re.search(r"rel\s*[:=]\s*[\"']?stylesheet|@import", w):
        return "stylesheet"
    if re.search(r"rel\s*[:=]\s*[\"']?(?:preconnect|dns-prefetch)", w):
        return "preconnect"
    if re.search(r"@font-face|src\s*:\s*url\($", w):
        return "font"
    if re.search(r"<script[^>]*$|\bsrc\s*:\s*[\"']$|import\(\s*[\"']$", w):
        return "script"
    if re.search(r"fetch\(\s*[\"'`]?$|xmlhttprequest|new websocket\(|eventsource\(", w):
        return "connect"
    if re.search(r"(?:<img|<video|<source|poster|_url[\"']?\s*:|image|video|url\()[^\n]*$", w):
        return "media"
    if re.search(r"href\s*[:=]\s*[\"'{]?$", w):
        return "link"
    return "reference"


def _origins(app: Path, files: list[str], live: set[str]) -> list[dict[str, Any]]:
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for rel in files:
        if not rel.endswith(TEXT_SUFFIXES) or rel.endswith(".md") or rel in LOCKFILES:
            continue
        text = _read_text(app, rel)
        masked = text
        if rel.endswith(CODE_SUFFIXES):
            try:
                masked = ts.scan(text).masked
            except ts.ScanError:
                pass
        for m in _URL.finditer(text):
            host = m.group(1).lower()
            if host in _IGNORED_HOSTS or (rel.endswith(CODE_SUFFIXES) and masked[m.start()] == " "):
                continue  # schema namespaces; URLs inside comments
            scheme = "http" if m.group(0).lower().startswith("http:") else "https"
            context = _url_context(text[max(0, m.start() - 160) : m.start()])
            key = (f"{scheme}://{host}", context)
            entry = found.setdefault(key, {"origin": key[0], "context": context, "files": set(), "live": False})
            entry["files"].add(rel)
            entry["live"] = entry["live"] or is_client_live(rel, live)
    return [{**v, "files": sorted(v["files"])} for _, v in sorted(found.items())]


def _fonts(app: Path, files: list[str], live: set[str]) -> list[dict[str, Any]]:
    fonts: dict[str, dict[str, Any]] = {}

    def add(entry: dict[str, Any]) -> None:
        fonts[json.dumps(entry, sort_keys=True)] = entry

    for rel in files:
        if rel not in live or not rel.endswith((*CODE_SUFFIXES, ".css")):
            continue
        text = _read_text(app, rel)
        for m in re.finditer(r"https://fonts\.googleapis\.com/css2?\?[^\"'\s)]+", text):
            for family in parse_qs(urlsplit(m.group(0)).query).get("family", []):
                name, _, axes = unquote(family).partition(":")
                weights = sorted(set(re.findall(r"(?<![\d.])\d{3}(?![\d.])", axes))) or ["400"]
                add(
                    {
                        "family": name.replace("+", " "),
                        "provider": "google-fonts",
                        "weights": weights,
                        "file": rel,
                        "delivery": "remote-stylesheet",
                    }
                )
        for m in re.finditer(r"https://api\.fontshare\.com/v2/css\?[^\"'\s)]+", text):
            for family, weights in re.findall(r"f(?:%5B%5D|\[\])=([\w-]+)@?([\d,]*)", m.group(0)):
                add(
                    {
                        "family": family,
                        "provider": "fontshare",
                        "weights": sorted(w for w in weights.split(",") if w),
                        "file": rel,
                        "delivery": "remote-stylesheet",
                    }
                )
        for m in re.finditer(r"@fontsource(?:-variable)?/([\w-]+)", text):
            add(
                {
                    "family": m.group(1),
                    "provider": "fontsource",
                    "weights": [],
                    "file": rel,
                    "delivery": "self-hosted-package",
                }
            )
        if rel.endswith(".css"):
            for m in re.finditer(r"@font-face\s*\{[^}]*font-family\s*:\s*[\"']?([^;\"']+)", text):
                add(
                    {
                        "family": m.group(1).strip(),
                        "provider": "local",
                        "weights": [],
                        "file": rel,
                        "delivery": "font-face",
                    }
                )
    return [fonts[k] for k in sorted(fonts)]


def _media(app: Path, files: list[str], live_texts: dict[str, str]) -> tuple[list, list, list]:
    images: list[dict[str, Any]] = []
    videos: list[dict[str, Any]] = []
    brand: list[dict[str, Any]] = []
    for rel in files:
        suffix = PurePosixPath(rel).suffix.lower()
        if suffix not in (*IMAGE_SUFFIXES, *VIDEO_SUFFIXES) or not rel.startswith(("public/", "src/")):
            continue
        needle = f"/{rel.removeprefix('public/')}" if rel.startswith("public/") else PurePosixPath(rel).name
        data = (app / rel).read_bytes()
        entry = {
            "path": rel,
            "sha256": sha256_hex(data),
            "bytes": len(data),
            "referenced_by": sorted(p for p, t in live_texts.items() if needle in t),
        }
        (videos if suffix in VIDEO_SUFFIXES else images).append(entry)
        stem = PurePosixPath(rel).stem.lower()
        if re.search(r"logo|mark|brand|favicon|apple-touch|icon-\d|android-chrome", stem):
            kind = "favicon" if re.search(r"favicon|apple-touch|android-chrome|icon-\d", stem) else "logo"
            brand.append(
                {"path": rel, "kind": kind, "sha256": entry["sha256"], "referenced_by": entry["referenced_by"]}
            )
    return images, videos, brand


def _rendered_brand_images(live_texts: dict[str, str]) -> list[dict[str, Any]]:
    found = []
    for rel, text in live_texts.items():
        if not rel.endswith((".tsx", ".jsx")):
            continue
        s = ts.scan(text)
        for img in ts.jsx_open_tags(s, "img"):
            own = " ".join(
                filter(None, (ts.jsx_attr(img, "className"), ts.jsx_attr(img, "id"), ts.jsx_attr(img, "src")))
            )
            anchor = ts.enclosing_tag(s, img.start, "a")
            around = (
                " ".join(filter(None, (ts.jsx_attr(anchor, "className"), ts.jsx_attr(anchor, "id")))) if anchor else ""
            )
            if re.search(r"logo|brand|mark", own, re.I) or re.search(r"brand|logo", around, re.I):
                found.append(
                    {
                        "path": ts.jsx_attr(img, "src") or "<dynamic>",
                        "kind": "rendered-brand-image",
                        "sha256": None,
                        "referenced_by": [rel],
                    }
                )
    return found


def _navigation(live_texts: dict[str, str]) -> list[dict[str, Any]]:
    nav: set[tuple[str, str, str]] = set()
    for rel, text in live_texts.items():
        if not rel.endswith(CODE_SUFFIXES):
            continue
        s = ts.scan(text)
        for tag_name, attr in (("a", "href"), ("Link", "to")):
            for tag in ts.jsx_open_tags(s, tag_name):
                target = ts.jsx_attr(tag, attr)
                if target is None:
                    continue
                if target.startswith("#"):
                    kind = "anchor"
                elif target.startswith("/"):
                    kind = "route"
                elif target.startswith(("mailto:", "tel:")):
                    kind = target.split(":", 1)[0]
                elif target.startswith(("http:", "https:")):
                    kind, target = "external", f"https://{urlsplit(target).hostname}"
                else:
                    kind = "other"
                nav.add((rel, target, kind))
    return [{"file": f, "target": t, "kind": k} for f, t, k in sorted(nav)]


def _security(app: Path, files: list[str], live: set[str], package: dict) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def add(code: str, path: str, detail: str, **extra: Any) -> None:
        is_live = path in live or not path.endswith(CODE_SUFFIXES)
        out.append({"code": code, "path": path, "detail": detail, "live": is_live, **extra})

    for rel in files:
        data = (app / rel).read_bytes()
        name = PurePosixPath(rel).name
        magic = next((kind for sig, kind in _BINARY_MAGIC.items() if data.startswith(sig)), None)
        media = rel.endswith((*IMAGE_SUFFIXES, *VIDEO_SUFFIXES, *FONT_SUFFIXES))
        if rel.endswith(_BINARY_SUFFIXES) or (magic and not media):
            add("binary_executable", rel, f"executable/binary file ({magic or PurePosixPath(rel).suffix})")
        if name in (".env", ".dev.vars") or name.startswith(".env."):
            add("environment_file", rel, "environment file shipped in the export")
        if name == ".npmrc":
            add("npmrc", rel, ".npmrc can redirect the registry or carry tokens")
        if not rel.endswith(TEXT_SUFFIXES) and name not in (".env", ".dev.vars", ".npmrc"):
            continue
        text = data.decode("utf-8", errors="replace")
        for kind, pattern in _SECRET_PATTERNS.items():
            for m in pattern.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                add("secret_like_string", rel, f"{kind} at line {line} (value not recorded)", kind=kind)
        if not (rel.endswith(CODE_SUFFIXES) and rel in live):
            continue
        try:
            masked = ts.scan(text).masked
        except ts.ScanError:
            add("unscannable_module", rel, "module structure could not be read safely")
            continue
        if re.search(r"\beval\s*\(|\bnew\s+Function\s*\(", masked):
            add("dynamic_code", rel, "eval / new Function")
        if "dangerouslySetInnerHTML" in masked:
            add("raw_html_injection", rel, "dangerouslySetInnerHTML")
        if re.search(r"createElement\(\s*[\"']script", text) or re.search(
            r"<script[^>]*\bsrc\s*=\s*[\"']https?:", text
        ):
            add("remote_script", rel, "creates or loads a remote <script>")
        if re.search(r"\bimport\(\s*[\"']https?:", text):
            add("remote_script", rel, "dynamic import from a URL")
        if re.search(r"scripts\s*:\s*\[[^\]]*\bsrc\s*:\s*[\"']https?:", text, re.S):
            add("remote_script", rel, "head() loads a remote script")
        if re.search(r"from\s+[\"']cloudflare:", text) or re.search(r"\bcreateServerFn\b", masked):
            add("server_runtime", rel, "server function / Cloudflare runtime binding")
        if re.search(r"\bprocess\.env\b", masked) and not re.search(r"(?:^|/)server\.[tj]sx?$|\.server\.[tj]sx?$", rel):
            add("process_env_access", rel, "process.env in a client-reachable module")
    for script, command in sorted(package.get("scripts", {}).items()):
        if script in LIFECYCLE_SCRIPTS:
            add("lifecycle_script", "package.json", f"{script}: {command}", script=script, command=command)
    if package.get("trustedDependencies"):
        add("trusted_dependencies", "package.json", "trustedDependencies would let dependency scripts run")
    return sorted(out, key=lambda f: (f["code"], f["path"], f["detail"]))


def inspect_source(app: Path, *, snapshot_zip_sha256: str, app_dir: str) -> SourceManifest:
    """Inspects the (read-only) exported app at `app`. Never executes it."""
    files = _files(app)
    package = json.loads(_read_text(app, "package.json"))
    deps = {**package.get("devDependencies", {}), **package.get("dependencies", {})}
    cleanup = analyze_cleanup(app)
    live_modules = set(cleanup.live_modules)
    live = live_modules | {f for f in files if f.startswith("src/") and f.endswith(".css")}
    live_texts = {rel: _read_text(app, rel) for rel in sorted(live) if (app / rel).is_file()}
    scripts = package.get("scripts", {})
    lockfile = next((name for name in LOCKFILES if name in files), None)
    code_files = [f for f in files if f.endswith(CODE_SUFFIXES)]

    server_fn_modules = sorted(
        m for m in code_files if re.search(r"\bcreateServerFn\b", _code_only(_read_text(app, m)))
    )
    forms: list[dict[str, Any]] = []
    for rel in (p for p in files if p.startswith("src/") and p.endswith((".tsx", ".jsx"))):
        text = _read_text(app, rel)
        if "<form" not in text:
            continue
        try:
            specs = {d.spec for d in ts.imports(ts.scan(text)) if resolve_spec(app, rel, d.spec) in server_fn_modules}
            forms += [{**form.to_dict(), "live": rel in live_modules} for form in discover_forms(rel, text, specs)]
        except ts.ScanError as exc:
            forms.append({"form_id": f"{rel}#?", "module": rel, "live": rel in live_modules, "error": str(exc)})

    images, videos, brand = _media(app, files, live_texts)
    brand += _rendered_brand_images(live_texts)

    meta_file = "src/app-meta.json" if "src/app-meta.json" in files else None
    metadata: dict[str, Any] = {"app_meta_file": meta_file, "app_meta_keys": [], "app_meta_external": []}
    if meta_file:
        meta = json.loads(_read_text(app, meta_file))
        metadata["app_meta_keys"] = sorted(meta)
        metadata["app_meta_external"] = [
            {"key": k, "origin": f"https://{urlsplit(v).hostname}"}
            for k, v in sorted(meta.items())
            if isinstance(v, str) and v.startswith(("http:", "https:"))
        ]
    metadata["head_modules"] = sorted(r for r, t in live_texts.items() if re.search(r"\bhead\s*:", t))

    structured = sorted(
        {r for r, t in live_texts.items() if "application/ld+json" in t}
        | {f for f in code_files if re.search(r"structured.?data", f, re.I)}
    )
    analytics = sorted(
        (
            {"vendor": vendor, "file": rel, "live": rel in live}
            for rel in files
            if rel.endswith((*CODE_SUFFIXES, ".html"))
            for vendor, pattern in _ANALYTICS.items()
            if pattern.search(_read_text(app, rel))
        ),
        key=lambda a: (a["vendor"], a["file"]),
    )
    host_hooks = sorted(
        (
            {"hook": hook, "file": rel}
            for rel, t in live_texts.items()
            for hook, p in _HOST_HOOKS.items()
            if p.search(t)
        ),
        key=lambda h: (h["hook"], h["file"]),
    )
    claims = [c for rel in sorted(live_texts) for c in detect_claims(rel, live_texts[rel])]
    if meta_file:
        claims += detect_claims(meta_file, _read_text(app, meta_file))

    tsconfig = json_loose(_read_text(app, "tsconfig.json")) if "tsconfig.json" in files else {}
    integration = {
        "root_route": next((f for f in ("src/routes/__root.tsx", "src/routes/__root.jsx") if f in files), None),
        "index_route": next((f for f in ("src/routes/index.tsx", "src/routes/index.jsx") if f in files), None),
        "vite_config": next((f for f in ("vite.config.ts", "vite.config.js", "vite.config.mjs") if f in files), None),
        "router": "src/router.tsx" if "src/router.tsx" in files else None,
        "tsconfig_paths": sorted((tsconfig.get("compilerOptions", {}) or {}).get("paths", {}) or {}),
        "server_function_modules": server_fn_modules,
        "server_only_modules": sorted(f for f in files if re.search(r"^src/.*\.server\.[tj]sx?$", f)),
        "footer_modules": sorted(r for r, t in live_texts.items() if r.endswith((".tsx", ".jsx")) and "<footer" in t),
        "stylesheets": sorted(f for f in live if f.endswith(".css")),
        "wrangler_config": next((f for f in ("wrangler.jsonc", "wrangler.toml", "wrangler.json") if f in files), None),
        "sql_migrations": sorted(f for f in files if f.endswith(".sql")),
    }
    already = sorted({marker for marker in _PLATFORM_MARKERS for t in live_texts.values() if marker in t})
    if any(f.startswith("src/platform/") for f in files):
        already.append("src/platform/")

    return SourceManifest(
        manifest_version=MANIFEST_VERSION,
        snapshot={
            "zip_sha256": snapshot_zip_sha256,
            "app_dir": app_dir,
            "files": len(files),
            "bytes": sum((app / f).stat().st_size for f in files),
        },
        framework={
            "dependencies": {n: deps[n] for n in FRAMEWORK_PACKAGES if n in deps},
            "router": "tanstack-file-routes"
            if "@tanstack/react-router" in deps and any(f.startswith("src/routes/") for f in files)
            else None,
            "typescript": "typescript" in deps,
            "module_type": package.get("type"),
        },
        package_manager={
            "lockfile": lockfile,
            "manager": LOCKFILES.get(lockfile or ""),
            "lockfile_sha256": sha256_hex((app / lockfile).read_bytes()) if lockfile else None,
        },
        build={
            "command": scripts.get("build"),
            "scripts": dict(sorted(scripts.items())),
            "expanded": build_commands(scripts, "build") if "build" in scripts else [],
        },
        dependencies=sorted(
            (
                {"name": n, "spec": str(v), "section": sec, "kind": _dependency_kind(str(v))}
                for sec in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
                for n, v in package.get(sec, {}).items()
            ),
            key=lambda d: (d["section"], d["name"]),
        ),
        modules={
            "total": len(code_files),
            "live": sorted(live_modules),
            "unavailable_packages": cleanup.unavailable_packages,
            "design_critical": cleanup.blocking,
            "removable_routes": cleanup.removed_routes,
            "removable_modules": len(cleanup.removed_modules),
        },
        routes=_routes(app, files, set(cleanup.removed_routes)),
        forms=sorted(forms, key=lambda f: f["form_id"]),
        navigation=_navigation(live_texts),
        images=images,
        videos=videos,
        fonts=_fonts(app, files, live),
        brand_assets=sorted(brand, key=lambda b: (b["kind"], b["path"], b["referenced_by"])),
        external_origins=_origins(app, files, live),
        analytics=analytics,
        host_hooks=host_hooks,
        metadata=metadata,
        structured_data=[{"file": f, "live": f in live} for f in structured],
        claims=claims,
        integration_points=integration,
        security=_security(app, files, live, package),
        already_adapted=already,
    )


def write_manifest(manifest: SourceManifest, path: Path) -> None:
    text = json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
