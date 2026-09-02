"""Drift guard for @generate-web-ai/workflow-config-types: re-runs the
same schema/fixture generation scripts/export_workflow_config_contract.py
performs and asserts the result is byte-identical to what's checked into
packages/workflow-config-types. If this fails, someone changed
app.domain.workflow_config without regenerating the TypeScript contract
(see that package's README) — Python stays the single source of truth
only if this stays in sync.
"""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parent.parent
OUTPUT_PACKAGE = REPO_ROOT / "packages" / "workflow-config-types"


def _load_export_script() -> ModuleType:
    script_path = API_ROOT / "scripts" / "export_workflow_config_contract.py"
    spec = importlib.util.spec_from_file_location("export_workflow_config_contract", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_schema_matches_the_current_pydantic_model():
    export = _load_export_script()
    schema_path = OUTPUT_PACKAGE / "schema" / "workflow-config.schema.json"

    regenerated = export._strip_titles(export.WorkflowConfig.model_json_schema(mode="serialization"))
    committed = json.loads(schema_path.read_text(encoding="utf-8"))

    assert regenerated == committed, (
        "packages/workflow-config-types/schema/workflow-config.schema.json is stale. "
        "Run: cd apps/api && uv run python scripts/export_workflow_config_contract.py, "
        "then: cd packages/workflow-config-types && node scripts/generate-types.mjs"
    )


def test_committed_fixture_matches_the_current_generator_output():
    export = _load_export_script()
    fixture_path = OUTPUT_PACKAGE / "fixtures" / "reforma-valencia-lead-capture.json"

    regenerated = export.generate_lead_capture_workflow(export.EXAMPLE_REFORMA_VALENCIA_CONFIG).model_dump(mode="json")
    committed = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert regenerated == committed, (
        "packages/workflow-config-types/fixtures/reforma-valencia-lead-capture.json is stale. "
        "Run: cd apps/api && uv run python scripts/export_workflow_config_contract.py"
    )


# Whether the checked-in workflow-config.ts itself is stale relative to
# the schema is verified on the TypeScript side, in
# packages/workflow-config-types/scripts/generate-types.test.ts — that
# check runs the real json-schema-to-typescript compile() and diffs it,
# rather than reimplementing that logic (or invoking Node) from here.
