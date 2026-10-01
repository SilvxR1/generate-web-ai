"""AdaptationPlan (H2): every change to an exported source, decided and
recorded BEFORE anything is mutated.

A plan is built by DRY-RUNNING each operation on an in-memory copy of the
source (VirtualTree), so it states exactly what each file will be before
and after (SHA-256) — an auditable, serializable description of the
adaptation, identified by its own SHA-256. `apply_plan` then replays the
same operations on the working copy and refuses on the first byte of
drift: a file that is not what the plan saw, or an edit that does not
produce what the plan predicted.

Four mechanical actions, all fail closed:

- add      a new file (never overwrites an existing one);
- remove   an existing file;
- replace  ONE exact fragment, which must occur exactly once;
- json     set/clear top-level keys of a JSON file, with optional
           expectations on the current values.

Structured transformations (import rewiring, JSX insertion, BusinessTruth
binding, prerender configuration...) are computed by the source-family
adapter from the source's structure and EXPRESSED as these actions, so
every modification is traceable to one operation, one category and one
reason, and the same inputs always produce the same plan.
"""

import base64
import hashlib
import json
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from app.creative.source_adapter.records import AdapterError, ChangeRecord, PatchMismatchError

PLAN_VERSION = "1.0.0"
# Bumped whenever the platform integration a plan adds (SDK, consent,
# legal, SEO, lead transport) changes what it produces.
PLATFORM_INTEGRATION_VERSION = "2.0.0"

CATEGORIES = frozenset(
    {
        "cleanup",
        "platform-sdk",
        "lead-transport",
        "consent",
        "legal",
        "seo",
        "assets",
        "fonts",
        "brand",
        "business-truth",
        "build",
        "approved-fix",
    }
)
# json_set value that removes the key (serializable).
DELETE_KEY: dict[str, bool] = {"$delete": True}


class PlanRefusedError(AdapterError):
    """The source cannot be adapted without a human decision (see findings)."""


class PlanDriftError(AdapterError):
    """The working copy is not what the plan was computed for."""


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(data: Any) -> bytes:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


@dataclass(frozen=True)
class Operation:
    op_id: str
    action: str  # add | remove | replace | json
    path: str
    category: str
    reason: str
    origin: str  # "family:<adapter>@<version>" | "overlay:<name>"
    visible: str | None = None  # visitor-visible effect, described
    find: str | None = None
    replace: str | None = None
    content: str | None = None  # added text file
    content_b64: str | None = None  # added binary file (summarized by its SHA-256 in the plan JSON)
    json_set: dict[str, Any] | None = None
    json_expect: dict[str, Any] | None = None  # key -> required current value ("prefix:<p>" = startswith)
    before_sha256: str | None = None
    after_sha256: str | None = None


class VirtualTree:
    """An in-memory copy of a source tree (relative POSIX path -> bytes)."""

    def __init__(self, files: dict[str, bytes]):
        self._files = dict(files)

    @classmethod
    def from_dir(cls, root: Path, *, exclude: tuple[str, ...] = ("node_modules/", "dist/")) -> "VirtualTree":
        files = {}
        for path in sorted(root.rglob("*")):
            if path.is_file():
                rel = path.relative_to(root).as_posix()
                if not rel.startswith(exclude):
                    files[rel] = path.read_bytes()
        return cls(files)

    def exists(self, path: str) -> bool:
        return path in self._files

    def read(self, path: str) -> bytes:
        if path not in self._files:
            raise PatchMismatchError(f"{path}: file not found")
        return self._files[path]

    def text(self, path: str) -> str:
        return self.read(path).decode("utf-8")

    def paths(self) -> list[str]:
        return sorted(self._files)

    def tree_sha256(self) -> str:
        return sha256_hex(canonical_json({p: sha256_hex(d) for p, d in sorted(self._files.items())}))

    def __iter__(self) -> Iterator[tuple[str, bytes]]:
        return iter(sorted(self._files.items()))

    def put(self, path: str, data: bytes | None) -> None:
        if data is None:
            self._files.pop(path, None)
        else:
            self._files[path] = data


def _exactly_once(text: str, fragment: str, where: str) -> None:
    count = text.count(fragment)
    if count != 1:
        raise PatchMismatchError(f"{where}: expected exactly one match, found {count}: {fragment[:100]!r}")


def _json_apply(raw: bytes, op: Operation) -> bytes:
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise PatchMismatchError(f"{op.path}: not a JSON object")
    for key, expected in (op.json_expect or {}).items():
        current = data.get(key)
        if isinstance(expected, str) and expected.startswith("prefix:"):
            if not isinstance(current, str) or not current.startswith(expected[7:]):
                raise PatchMismatchError(f"{op.path}: {key!r} does not start with {expected[7:]!r}")
        elif current != expected:
            raise PatchMismatchError(f"{op.path}: {key!r} is {current!r}, expected {expected!r}")
    for key, value in (op.json_set or {}).items():
        if value == DELETE_KEY:
            data.pop(key, None)
        else:
            data[key] = value
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def execute(before: bytes | None, op: Operation) -> bytes | None:
    """The pure effect of one operation on one file's bytes (None = absent)."""
    if op.action == "add":
        if before is not None:
            raise AdapterError(f"{op.path}: refusing to overwrite an existing source file")
        if op.content_b64 is not None:
            return base64.b64decode(op.content_b64)
        if op.content is None:
            raise AdapterError(f"{op.path}: add without content")
        return op.content.encode("utf-8")
    if before is None:
        raise PatchMismatchError(f"{op.path}: file not found")
    if op.action == "remove":
        return None
    if op.action == "replace":
        if op.find is None or op.replace is None:
            raise AdapterError(f"{op.path}: replace without find/replace")
        text = before.decode("utf-8")
        _exactly_once(text, op.find, op.path)
        return text.replace(op.find, op.replace, 1).encode("utf-8")
    if op.action == "json":
        return _json_apply(before, op)
    raise AdapterError(f"unknown plan action {op.action!r}")


class PlanBuilder:
    """Dry-runs operations on a VirtualTree and records them, numbered, with
    their before/after SHA-256."""

    def __init__(self, tree: VirtualTree, origin: str):
        self.tree = tree
        self.origin = origin
        self.operations: list[Operation] = []

    def _record(self, op: Operation) -> Operation:
        if op.category not in CATEGORIES:
            raise AdapterError(f"unknown plan category {op.category!r}")
        before = self.tree._files.get(op.path)
        after = execute(before, op)
        numbered = replace(
            op,
            op_id=f"{len(self.operations) + 1:03d}-{op.category}",
            before_sha256=None if before is None else sha256_hex(before),
            after_sha256=None if after is None else sha256_hex(after),
        )
        self.tree.put(op.path, after)
        self.operations.append(numbered)
        return numbered

    def add(
        self,
        path: str,
        content: str | bytes,
        *,
        category: str,
        reason: str,
        visible: str | None = None,
        origin: str | None = None,
    ) -> Operation:
        who = origin or self.origin
        if isinstance(content, bytes):
            encoded = base64.b64encode(content).decode()
            return self._record(Operation("", "add", path, category, reason, who, visible, content_b64=encoded))
        return self._record(Operation("", "add", path, category, reason, who, visible, content=content))

    def remove(self, path: str, *, category: str, reason: str, origin: str | None = None) -> Operation:
        return self._record(Operation("", "remove", path, category, reason, origin or self.origin))

    def replace(
        self,
        path: str,
        find: str,
        new: str,
        *,
        category: str,
        reason: str,
        visible: str | None = None,
        origin: str | None = None,
    ) -> Operation:
        return self._record(
            Operation("", "replace", path, category, reason, origin or self.origin, visible, find=find, replace=new)
        )

    def json(
        self,
        path: str,
        values: dict[str, Any],
        *,
        category: str,
        reason: str,
        expect: dict[str, Any] | None = None,
        visible: str | None = None,
        origin: str | None = None,
    ) -> Operation:
        return self._record(
            Operation(
                "", "json", path, category, reason, origin or self.origin, visible, json_set=values, json_expect=expect
            )
        )


@dataclass
class AdaptationPlan:
    plan_version: str
    platform_integration_version: str
    adapter: dict[str, str]  # adapter_id, version, contract_version, family
    overlay: dict[str, str] | None
    snapshot_zip_sha256: str
    manifest_sha256: str
    business_truth_sha256: str
    site: dict[str, str]  # origin, locale
    supportability: dict[str, Any]
    form_mappings: list[dict[str, Any]]
    fact_bindings: list[dict[str, Any]]
    fact_ledger: dict[str, str]
    csp: dict[str, Any]
    build: dict[str, Any]
    approvals: list[dict[str, str]]  # review findings a human approved (overlay)
    readiness_findings: list[dict[str, str]]
    operations: list[Operation]
    source_tree_sha256: str  # the working copy the plan starts from
    adapted_tree_sha256: str  # the predicted result
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, include_binary: bool = False) -> dict[str, Any]:
        data = asdict(self)
        ops = []
        for op in self.operations:
            entry = {k: v for k, v in asdict(op).items() if v is not None}
            if "content_b64" in entry and not include_binary:
                entry.pop("content_b64")
                entry["binary"] = True
            ops.append(entry)
        data["operations"] = ops
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AdaptationPlan":
        """The inverse of to_dict(include_binary=True) — the worker rebuilds
        the exact stored plan (its plan_sha256 must equal the job's)."""
        values = {k: v for k, v in data.items() if k != "plan_sha256"}
        operations = []
        for entry in values.pop("operations"):
            if entry.get("binary") and "content_b64" not in entry:
                raise AdapterError(f"{entry.get('path')}: binary content missing from the serialized plan")
            operations.append(Operation(**{k: v for k, v in entry.items() if k != "binary"}))
        return cls(**values, operations=operations)

    @property
    def plan_sha256(self) -> str:
        """Identity of the plan: every operation (binary content by its
        after_sha256), every input identity and every decision."""
        return sha256_hex(canonical_json(self.to_dict()))

    def changed_files(self) -> list[str]:
        return sorted({op.path for op in self.operations if op.before_sha256 != op.after_sha256})


def apply_plan(app: Path, plan: AdaptationPlan) -> list[ChangeRecord]:
    """Replays `plan` on the working copy at `app`. Stops (PlanDriftError)
    before writing anything that is not exactly what the plan predicted —
    so a plan can never be applied twice, or to a different source."""
    if VirtualTree.from_dir(app).tree_sha256() != plan.source_tree_sha256:
        raise PlanDriftError("the working copy is not the source this plan was computed for")
    changes: list[ChangeRecord] = []
    for op in plan.operations:
        target = app / op.path
        before = target.read_bytes() if target.is_file() else None
        if (None if before is None else sha256_hex(before)) != op.before_sha256:
            raise PlanDriftError(f"{op.op_id} {op.path}: file differs from the plan")
        after = execute(before, op)
        if (None if after is None else sha256_hex(after)) != op.after_sha256:
            raise PlanDriftError(f"{op.op_id} {op.path}: result differs from the plan")
        if after is None:
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(after)
        changes.append(
            ChangeRecord(
                op.path,
                f"{op.action}:{op.category}",
                f"[{op.op_id}] {op.reason}",
                op.visible,
                op.before_sha256,
                op.after_sha256,
            )
        )
    if VirtualTree.from_dir(app).tree_sha256() != plan.adapted_tree_sha256:
        raise PlanDriftError("the adapted working copy differs from the plan's predicted result")
    return changes
