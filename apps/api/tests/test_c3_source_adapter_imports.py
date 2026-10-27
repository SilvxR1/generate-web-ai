"""C3 — the source adapter never imports the same binding twice.

Cositas y Puntos v3 (a real Higgsfield export) renders its logo in
src/routes/index.tsx. The SEO step added
`import { BUSINESS, SITE_JSONLD } from "../platform/business";` and the brand
step then added `import { BUSINESS } from "../platform/business";` to the same
module, because `ensure_import` compared whole lines: the isolated build
failed with "Identifier 'BUSINESS' has already been declared". Imports are
now compared by binding.
"""

import json
import shutil
from pathlib import Path

import pytest

from app.creative.source_adapter import tsx_scan as ts
from app.creative.source_adapter.edits import ensure_import
from app.creative.source_adapter.fixtures import lumen_physio_business_config, zip_directory
from app.creative.source_adapter.pipeline import plan_export
from app.creative.source_adapter.plan import PlanBuilder, VirtualTree, execute
from app.creative.source_adapter.records import AdapterError

FIXTURE = Path(__file__).parent / "fixtures" / "higgsfield_synthetic" / "lumen-physio"
ORIGIN = "https://lumen-physio.example"
INDEX = "src/routes/index.tsx"


def _builder(source: str) -> PlanBuilder:
    return PlanBuilder(VirtualTree({INDEX: source.encode()}), "family:test")


def _ensure(builder: PlanBuilder, statement: str):
    return ensure_import(builder, INDEX, statement, category="brand", reason="test")


def _bindings(text: str) -> list[str]:
    return [name for decl in ts.imports(ts.scan(text)) for name in ts.imported_names(decl.clause)]


SOURCE = 'import { useState } from "react";\nimport { BUSINESS, SITE_JSONLD } from "../platform/business";\n\nx;\n'


# --- ensure_import ----------------------------------------------------------------------------


def test_a_name_already_imported_from_the_same_module_is_not_imported_again():
    builder = _builder(SOURCE)
    assert _ensure(builder, 'import { BUSINESS } from "../platform/business";') is None
    assert builder.tree.text(INDEX) == SOURCE and builder.operations == []


@pytest.mark.parametrize(
    "existing",
    [
        "import {BUSINESS} from '../platform/business'\n",
        'import {\n  SITE_JSONLD,\n  BUSINESS,\n} from "../platform/business";\n',
        'import { type Foo, BUSINESS } from "../platform/business";\n',
    ],
)
def test_the_existing_import_may_be_formatted_differently(existing):
    builder = _builder(f'import {{ useState }} from "react";\n{existing}\nx;\n')
    assert _ensure(builder, 'import { BUSINESS } from "../platform/business";') is None


def test_only_the_missing_names_are_added():
    builder = _builder('import { BUSINESS } from "../platform/business";\n\nx;\n')
    _ensure(builder, 'import { BUSINESS, SITE_JSONLD } from "../platform/business";')
    text = builder.tree.text(INDEX)
    assert 'import { SITE_JSONLD } from "../platform/business";\n' in text
    assert sorted(_bindings(text)) == ["BUSINESS", "SITE_JSONLD"]


def test_a_new_import_is_still_added_after_the_last_import():
    builder = _builder('import { useState } from "react";\n\nx;\n')
    _ensure(builder, 'import { BUSINESS } from "../platform/business";')
    assert builder.tree.text(INDEX) == (
        'import { useState } from "react";\nimport { BUSINESS } from "../platform/business";\n\nx;\n'
    )


def test_a_side_effect_import_is_added_once():
    builder = _builder("import './lib/platform-sdk'\n\nx;\n")
    assert _ensure(builder, 'import "./lib/platform-sdk";') is None
    _ensure(builder, 'import "./other";')
    assert builder.tree.text(INDEX).count('import "./other";') == 1


def test_a_name_bound_by_another_module_is_refused_not_duplicated():
    builder = _builder('import { BUSINESS } from "./somewhere-else";\n\nx;\n')
    with pytest.raises(AdapterError, match="BUSINESS"):
        _ensure(builder, 'import { BUSINESS } from "../platform/business";')
    assert builder.operations == []


def test_a_default_import_compares_by_its_local_name():
    builder = _builder('import fraunces from "@fontsource/fraunces/600.css?url";\n\nx;\n')
    assert _ensure(builder, "import fraunces from '@fontsource/fraunces/600.css?url';") is None


# --- the Cositas v3 shape, through the real plan ----------------------------------------------


def test_a_logo_rendered_in_the_index_route_gets_one_business_import(tmp_path):
    """Lumen with its logo in index.tsx — the exact Cositas v3 layout."""
    source = tmp_path / "v" / "lumen-physio"
    shutil.copytree(FIXTURE, source)
    index = source / INDEX
    text = index.read_text(encoding="utf-8")
    logo = '<a className="brand" href="/"><img alt="" src="/brand/lumen-logo.svg" width={28} height={28} /></a>'
    index.write_text(text.replace("      <SiteHeader />", f"      {logo}\n      <SiteHeader />"), encoding="utf-8")
    zip_path = zip_directory(source, tmp_path / "v.zip")
    work = tmp_path / "work"
    planned = plan_export(zip_path, work, lumen_physio_business_config(), site_origin=ORIGIN)

    tree = VirtualTree.from_dir(work / "original" / "lumen-physio")
    for op in planned.plan.operations:
        tree.put(op.path, execute(tree._files.get(op.path), op))
    adapted = tree.text(INDEX)
    assert "src={BUSINESS.logo.src}" in adapted  # the brand step did run on the index route
    assert "SITE_JSONLD" in adapted  # and so did the SEO step
    names = _bindings(adapted)
    assert names.count("BUSINESS") == 1, adapted[:600]
    assert len(names) == len(set(names))  # no identifier is declared twice by an import
    plan = json.loads((work / "adaptation-plan.json").read_text(encoding="utf-8"))
    assert plan["supportability"] != "UNSUPPORTED"
