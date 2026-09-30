"""SourceInventory (H1): an immutable, hash-identified snapshot of an
exported website source (the ZIP an external builder such as Higgsfield
Supercomputer exports).

The ZIP is untrusted input. It is never `extractall`ed: every member is
checked (no absolute paths, no `..`, no symlinks or special files, bounded
count and size) and written by this code. The extracted tree is then made
read-only — it is the ORIGINAL; every adaptation happens on a copy.
"""

import json
import stat
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

from app.creative.source_adapter.records import AdapterError, sha256_hex

MAX_ENTRIES = 5000
MAX_FILE_BYTES = 64 * 1024**2
MAX_TOTAL_BYTES = 512 * 1024**2
_ASSET_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".ico", ".mp4", ".webm", ".woff", ".woff2", ".ttf", ".otf"}
)
_LOCKFILES = {"bun.lock": "bun", "bun.lockb": "bun", "package-lock.json": "npm", "pnpm-lock.yaml": "pnpm"}


class UnsafeArchiveError(AdapterError):
    """The export archive contains an entry this code refuses to extract."""


@dataclass(frozen=True)
class SourceFile:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class SourceSnapshot:
    zip_sha256: str
    zip_size: int
    root: Path  # the extracted, read-only tree
    app_dir: str  # relative directory holding package.json
    files: tuple[SourceFile, ...]
    package_manager: str | None
    lockfile: str | None
    lockfile_sha256: str | None
    build_command: str | None
    framework: dict[str, str] = field(default_factory=dict)

    @property
    def assets(self) -> tuple[SourceFile, ...]:
        return tuple(f for f in self.files if PurePosixPath(f.path).suffix.lower() in _ASSET_SUFFIXES)

    def manifest(self) -> dict:
        data = asdict(self)
        data["root"] = str(self.root)
        data["files"] = [asdict(f) for f in self.files]
        data["assets"] = {
            "count": len(self.assets),
            "bytes": sum(a.size for a in self.assets),
            "files": [asdict(a) for a in self.assets],
        }
        return data


def _safe_member_path(info: zipfile.ZipInfo) -> PurePosixPath:
    name = info.filename
    path = PurePosixPath(name)
    mode = info.external_attr >> 16
    if name.startswith("/") or (len(name) > 1 and name[1] == ":") or "\\" in name:
        raise UnsafeArchiveError(f"absolute or non-POSIX path in archive: {name!r}")
    if any(part in ("..", "") for part in path.parts):
        raise UnsafeArchiveError(f"path traversal in archive: {name!r}")
    # Many writers store permission bits without a file type (type 0): only a
    # DECLARED non-regular type (symlink, device, fifo, socket) is refused.
    file_type = stat.S_IFMT(mode)
    if file_type and file_type not in (stat.S_IFREG, stat.S_IFDIR):
        raise UnsafeArchiveError(f"symlink or special file in archive: {name!r}")
    return path


def _extract(zip_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        members = archive.infolist()
        if len(members) > MAX_ENTRIES:
            raise UnsafeArchiveError(f"archive has {len(members)} entries (limit {MAX_ENTRIES})")
        total = 0
        seen: set[str] = set()
        for info in members:
            path = _safe_member_path(info)
            if info.is_dir():
                continue
            if str(path) in seen:
                raise UnsafeArchiveError(f"duplicate entry in archive: {info.filename!r}")
            seen.add(str(path))
            if info.file_size > MAX_FILE_BYTES:
                raise UnsafeArchiveError(f"archive entry too large: {info.filename!r}")
            total += info.file_size
            if total > MAX_TOTAL_BYTES:
                raise UnsafeArchiveError("archive exceeds the total extracted size limit")
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source:
                data = source.read(MAX_FILE_BYTES + 1)
            if len(data) > MAX_FILE_BYTES:
                raise UnsafeArchiveError(f"archive entry too large: {info.filename!r}")
            target.write_bytes(data)


def _make_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        path.chmod(0o555 if path.is_dir() else 0o444)
    root.chmod(0o555)


def snapshot_export(zip_path: Path, destination: Path) -> SourceSnapshot:
    """Extracts `zip_path` into `destination` (which must not exist), hashes
    every file and returns the snapshot. `destination` ends up read-only."""
    if destination.exists():
        raise AdapterError(f"snapshot destination already exists: {destination}")
    zip_bytes = zip_path.read_bytes()
    destination.mkdir(parents=True)
    _extract(zip_path, destination)

    files = tuple(
        SourceFile(path.relative_to(destination).as_posix(), sha256_hex(path.read_bytes()), path.stat().st_size)
        for path in sorted(destination.rglob("*"))
        if path.is_file()
    )
    manifests = [f.path for f in files if PurePosixPath(f.path).name == "package.json" and "node_modules" not in f.path]
    if len(manifests) != 1:
        raise AdapterError(f"expected exactly one package.json in the export, found {len(manifests)}")
    app_dir = str(PurePosixPath(manifests[0]).parent)
    package = json.loads((destination / manifests[0]).read_text(encoding="utf-8"))
    dependencies = {**package.get("devDependencies", {}), **package.get("dependencies", {})}
    framework = {
        name: dependencies[name]
        for name in ("react", "@tanstack/react-start", "vite", "tailwindcss", "astro", "next")
        if name in dependencies
    }
    lockfile = next((name for name in _LOCKFILES if (destination / app_dir / name).is_file()), None)
    snapshot = SourceSnapshot(
        zip_sha256=sha256_hex(zip_bytes),
        zip_size=len(zip_bytes),
        root=destination,
        app_dir=app_dir,
        files=files,
        package_manager=_LOCKFILES[lockfile] if lockfile else None,
        lockfile=lockfile,
        lockfile_sha256=sha256_hex((destination / app_dir / lockfile).read_bytes()) if lockfile else None,
        build_command=package.get("scripts", {}).get("build"),
        framework=framework,
    )
    _make_read_only(destination)
    return snapshot
