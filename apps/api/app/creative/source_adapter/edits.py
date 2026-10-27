"""Positional edits expressed as exact-once plan operations (H2).

A structural analysis (tsx_scan) locates WHERE to change a file; these
helpers turn that position into a `replace` operation whose `find` is the
smallest run of whole lines around it that occurs exactly once in the
file. The plan therefore records a readable, reviewable diff, and the
edit can only ever apply to that one place.
"""

import posixpath
import re

from app.creative.source_adapter import tsx_scan as ts
from app.creative.source_adapter.plan import Operation, PlanBuilder
from app.creative.source_adapter.records import AdapterError


def unique_window(text: str, start: int, end: int) -> tuple[int, int]:
    """Whole-line window containing [start, end) that occurs exactly once."""
    a = text.rfind("\n", 0, start) + 1
    b = text.find("\n", end)
    b = len(text) if b == -1 else b + 1
    while text.count(text[a:b]) != 1:
        if a == 0 and b == len(text):
            raise AdapterError("no unique context for an edit")
        if a > 0:
            a = text.rfind("\n", 0, a - 1) + 1
        if b < len(text):
            nxt = text.find("\n", b)
            b = len(text) if nxt == -1 else nxt + 1
    return a, b


def edit_span(
    builder: PlanBuilder,
    path: str,
    start: int,
    end: int,
    new: str,
    *,
    category: str,
    reason: str,
    visible: str | None = None,
) -> Operation:
    """Replace text[start:end] of `path` (current plan state) with `new`."""
    text = builder.tree.text(path)
    a, b = unique_window(text, start, end)
    window = text[a:b]
    replaced = window[: start - a] + new + window[end - a :]
    return builder.replace(path, window, replaced, category=category, reason=reason, visible=visible)


def relative_import(from_module: str, to_module: str) -> str:
    """The relative specifier from `from_module` to `to_module` (no extension)."""
    target = posixpath.splitext(to_module)[0]
    spec = posixpath.relpath(target, posixpath.dirname(from_module))
    return spec if spec.startswith(".") else f"./{spec}"


def ensure_import(builder: PlanBuilder, path: str, statement: str, *, category: str, reason: str) -> Operation | None:
    """Adds `statement` (one full import line) after the module's last
    import. Compared by binding, not by text: names the module already
    imports from the same specifier (in any statement, however formatted)
    are not imported again, and only the missing names of a `{ ... }`
    clause are added. A name already bound by an import of ANOTHER module
    is refused — the result would not compile (duplicate identifier)."""
    text = builder.tree.text(path)
    line = statement if statement.endswith("\n") else statement + "\n"
    if line in text:
        return None
    wanted = ts.imports(ts.scan(line))
    if len(wanted) != 1:
        raise AdapterError(f"not a single import statement: {statement!r}")
    want = wanted[0]
    decls = ts.imports(ts.scan(text))
    names = ts.imported_names(want.clause)
    if not names:
        if any(d.spec == want.spec and d.clause is None for d in decls):
            return None
    else:
        bound = {name: d.spec for d in decls for name in ts.imported_names(d.clause)}
        clash = sorted(n for n in names if n in bound and bound[n] != want.spec)
        if clash:
            raise AdapterError(f"{path}: {clash} already imported from another module than {want.spec!r}")
        missing = [n for n in names if n not in bound]
        if not missing:
            return None
        if missing != names:
            named = re.fullmatch(r"\{([^}]*)\}", (want.clause or "").strip())
            if named is None:
                raise AdapterError(f"{path}: cannot add part of {statement!r}")
            parts = [p.strip() for p in named.group(1).split(",") if p.strip()]
            kept = [p for p in parts if p.removeprefix("type ").strip().split(" as ")[-1].strip() in missing]
            line = f'import {{ {", ".join(kept)} }} from "{want.spec}";\n'
    at = decls[-1].end if decls else 0
    return edit_span(builder, path, at, at, line, category=category, reason=reason)


def line_indent(text: str, index: int) -> str:
    line_start = text.rfind("\n", 0, index) + 1
    line = text[line_start:index]
    return line[: len(line) - len(line.lstrip())]
