"""SourceMapping (H1): the source-specific half of the adapter — fixed data
for ONE export, applied in a fixed order by apply_mapping:

    removed backend files -> patches -> JSON field patches -> added dependencies -> new
    platform files -> BusinessTruth bindings

Every step is a records.py primitive, so every change is recorded with its
before/after SHA-256 and any drift in the export stops the adapter.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.creative.source_adapter.records import (
    AdapterError,
    ChangeRecord,
    ContentBinding,
    JsonFieldPatch,
    NewFile,
    SourcePatch,
    apply_binding,
    apply_json_field,
    apply_patch,
    remove_file,
    sha256_hex,
    write_new_file,
)
from app.domain.business_truth import BusinessTruth
from app.publishing.csp_policy import validate_requested
from app.publishing.security_headers import CspExtensions


@dataclass(frozen=True)
class SourceMapping:
    name: str
    export_zip_sha256: str
    # H1.1: the trusted family (app.publishing.csp_policy) and what THIS
    # source says it needs; resolved_csp() accepts it only inside the family
    # policy and returns that policy (fail closed otherwise).
    source_family: str
    csp_requirements: CspExtensions
    added_dependencies: dict[str, str]
    removed_files: tuple[str, ...]
    patches: tuple[SourcePatch, ...]
    bindings: tuple[ContentBinding, ...]
    new_files: Callable[[BusinessTruth], list[NewFile]]
    truth_values: Callable[[BusinessTruth], dict[str, str]]
    unbound_content: tuple[str, ...] = ()
    json_fields: tuple[JsonFieldPatch, ...] = ()


def resolved_csp(mapping: SourceMapping) -> CspExtensions:
    """The single CSP policy the artifact's `_headers` are derived from."""
    return validate_requested(mapping.source_family, mapping.csp_requirements)


def _add_dependencies(app: Path, dependencies: dict[str, str]) -> ChangeRecord:
    path = app / "package.json"
    raw = path.read_text(encoding="utf-8")
    package = json.loads(raw)
    deps = package.setdefault("dependencies", {})
    for name, version in dependencies.items():
        if name in deps:
            raise AdapterError(f"{name} is already a dependency of the export")
        deps[name] = version
    package["dependencies"] = dict(sorted(deps.items()))
    updated = json.dumps(package, indent=2, ensure_ascii=False) + "\n"
    path.write_text(updated, encoding="utf-8")
    return ChangeRecord(
        "package.json",
        "dependency",
        "added platform dependencies: " + ", ".join(f"{n}@{v}" for n, v in dependencies.items()),
        None,
        sha256_hex(raw.encode()),
        sha256_hex(updated.encode()),
    )


def apply_mapping(app: Path, mapping: SourceMapping, truth: BusinessTruth) -> list[ChangeRecord]:
    changes = [
        remove_file(app, relative, reason="Higgsfield server backend replaced by the GWA public Lead API")
        for relative in mapping.removed_files
    ]
    changes += [apply_patch(app, patch) for patch in mapping.patches]
    changes += [apply_json_field(app, field) for field in mapping.json_fields]
    if mapping.added_dependencies:
        changes.append(_add_dependencies(app, mapping.added_dependencies))
    changes += [write_new_file(app, new) for new in mapping.new_files(truth)]
    values = mapping.truth_values(truth)
    changes += [apply_binding(app, binding, values[binding.field]) for binding in mapping.bindings]
    return changes
