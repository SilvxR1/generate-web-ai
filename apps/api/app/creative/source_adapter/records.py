"""Traceable, deterministic source modifications (H1).

Every change the adapter makes to an exported website's source is one of
four primitives, each recorded as a ChangeRecord with the file's SHA-256
before and after:

- SourcePatch: replace ONE exact fragment. The fragment must occur exactly
  once, otherwise the adapter stops (PatchMismatchError) — a changed export
  is never "patched somewhere nearby".
- ContentBinding: replace a business-fact literal inside ONE exact fragment
  with the BusinessTruth value (e.g. the business name in the footer).
- NewFile / removal: platform-owned files added, dead code removed.

There is no free-form rewriting: the set of edits is fixed data, so the same
export always produces the same adapted source.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path


class AdapterError(Exception):
    """The adapter cannot proceed safely; nothing downstream may continue."""


class PatchMismatchError(AdapterError):
    """A patch/binding fragment was not found exactly once."""


@dataclass(frozen=True)
class ChangeRecord:
    path: str
    kind: str  # cleanup-remove | cleanup-edit | patch | add | remove | binding | dependency
    reason: str
    visible: str | None = None  # visitor-visible effect, described; None = not visible
    before_sha256: str | None = None
    after_sha256: str | None = None


@dataclass(frozen=True)
class SourcePatch:
    path: str
    find: str
    replace: str
    reason: str
    visible: str | None = None


@dataclass(frozen=True)
class JsonFieldPatch:
    """Set top-level `key` of the JSON file `path` to `value`, only if its
    current value is a string starting with `expected_prefix` (e.g. a
    builder-hosted CDN URL, matched by host so no account path is needed)."""

    path: str
    key: str
    expected_prefix: str
    value: object
    reason: str
    visible: str | None = None


@dataclass(frozen=True)
class NewFile:
    path: str
    content: str
    reason: str
    visible: str | None = None


@dataclass(frozen=True)
class ContentBinding:
    """`literal` inside `fragment` (which must occur exactly once in `path`)
    is the value of BusinessTruth `field`."""

    path: str
    fragment: str
    literal: str
    field: str


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha(path: Path) -> str | None:
    return sha256_hex(path.read_bytes()) if path.is_file() else None


def _exactly_once(text: str, fragment: str, *, where: str) -> None:
    count = text.count(fragment)
    if count != 1:
        raise PatchMismatchError(f"{where}: expected exactly one match, found {count}: {fragment[:80]!r}")


def apply_patch(root: Path, patch: SourcePatch) -> ChangeRecord:
    target = root / patch.path
    before = _file_sha(target)
    if before is None:
        raise PatchMismatchError(f"{patch.path}: file not found")
    text = target.read_text(encoding="utf-8")
    _exactly_once(text, patch.find, where=patch.path)
    target.write_text(text.replace(patch.find, patch.replace, 1), encoding="utf-8")
    return ChangeRecord(patch.path, "patch", patch.reason, patch.visible, before, _file_sha(target))


def apply_json_field(root: Path, patch: JsonFieldPatch) -> ChangeRecord:
    target = root / patch.path
    before = _file_sha(target)
    if before is None:
        raise PatchMismatchError(f"{patch.path}: file not found")
    data = json.loads(target.read_text(encoding="utf-8"))
    current = data.get(patch.key) if isinstance(data, dict) else None
    if not isinstance(current, str) or not current.startswith(patch.expected_prefix):
        raise PatchMismatchError(f"{patch.path}: {patch.key!r} does not start with {patch.expected_prefix!r}")
    data[patch.key] = patch.value
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return ChangeRecord(patch.path, "patch", patch.reason, patch.visible, before, _file_sha(target))


def write_new_file(root: Path, new: NewFile) -> ChangeRecord:
    target = root / new.path
    if target.exists():
        raise AdapterError(f"{new.path}: refusing to overwrite an existing source file")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(new.content, encoding="utf-8")
    return ChangeRecord(new.path, "add", new.reason, new.visible, None, _file_sha(target))


def remove_file(root: Path, relative: str, *, reason: str, kind: str = "remove") -> ChangeRecord:
    target = root / relative
    before = _file_sha(target)
    if before is None:
        raise AdapterError(f"{relative}: cannot remove a file that does not exist")
    target.unlink()
    return ChangeRecord(relative, kind, reason, None, before, None)


# A bound value is written into TS/TSX/JSON string or JSX-text positions:
# anything that could change the surrounding syntax is refused, never escaped.
_UNSAFE_VALUE = re.compile(r"[{}<>\"'`\\\n\r]")


def apply_binding(root: Path, binding: ContentBinding, value: str) -> ChangeRecord:
    if not value.strip() or _UNSAFE_VALUE.search(value):
        raise AdapterError(f"{binding.field}: value cannot be bound safely into {binding.path}")
    target = root / binding.path
    before = _file_sha(target)
    if before is None:
        raise PatchMismatchError(f"{binding.path}: file not found")
    text = target.read_text(encoding="utf-8")
    _exactly_once(text, binding.fragment, where=binding.path)
    _exactly_once(binding.fragment, binding.literal, where=f"{binding.path} fragment")
    bound = binding.fragment.replace(binding.literal, value, 1)
    target.write_text(text.replace(binding.fragment, bound, 1), encoding="utf-8")
    return ChangeRecord(
        binding.path,
        "binding",
        f"BusinessTruth {binding.field} = {value!r} (source literal {binding.literal!r})",
        None if value == binding.literal else f"{binding.literal!r} -> {value!r}",
        before,
        _file_sha(target),
    )
