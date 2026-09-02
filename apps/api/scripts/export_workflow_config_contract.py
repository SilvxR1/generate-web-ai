"""Exports the WorkflowConfig contract for the TypeScript side to consume
— the same minimal Pydantic -> JSON Schema -> TS-types bridge already
used for BusinessConfig (see packages/business-config-types), applied to
the workflow side rather than a second, hand-maintained TypeScript
WorkflowConfig definition (which had drifted from app.domain.workflow_config
before this script existed).

Writes:
  packages/workflow-config-types/schema/workflow-config.schema.json
  packages/workflow-config-types/fixtures/reforma-valencia-lead-capture.json

Run after any change to app.domain.workflow_config, then regenerate the
TypeScript types (see that package's README) — manual and explicit, not
wired into any build, so the JS side never needs Python present.
"""

import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))  # so `uv run python scripts/...` works without a separate PYTHONPATH

from app.domain.business_config import EXAMPLE_REFORMA_VALENCIA_CONFIG  # noqa: E402
from app.domain.workflow_config import WorkflowConfig, generate_lead_capture_workflow  # noqa: E402

REPO_ROOT = API_ROOT.parent.parent
OUTPUT_PACKAGE = REPO_ROOT / "packages" / "workflow-config-types"


def _strip_titles(node: object, parent_key: str | None = None) -> object:
    """Same rationale as export_business_config_contract.py's helper of
    the same name: drop Pydantic's auto-generated per-field `title`
    (noise json-schema-to-typescript would otherwise hoist into its own
    single-field type alias) while never touching a `properties`/`$defs`
    key that happens to be spelled "title"."""
    if isinstance(node, dict):
        if parent_key in ("properties", "$defs"):
            return {key: _strip_titles(value) for key, value in node.items()}
        return {key: _strip_titles(value, parent_key=key) for key, value in node.items() if key != "title"}
    if isinstance(node, list):
        return [_strip_titles(item) for item in node]
    return node


def main() -> None:
    schema_path = OUTPUT_PACKAGE / "schema" / "workflow-config.schema.json"
    fixture_path = OUTPUT_PACKAGE / "fixtures" / "reforma-valencia-lead-capture.json"
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.parent.mkdir(parents=True, exist_ok=True)

    # mode="serialization" (not the default "validation"): WorkflowConfig
    # is consumed by Studio purely as API *output* (never constructed and
    # sent back), and `required_capabilities` is a `@computed_field` —
    # present in what the model serializes to, entirely absent from what
    # it accepts to validate. The default mode would silently drop it.
    schema = _strip_titles(WorkflowConfig.model_json_schema(mode="serialization"))
    schema_path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    fixture_workflow = generate_lead_capture_workflow(EXAMPLE_REFORMA_VALENCIA_CONFIG)
    fixture_json = json.dumps(fixture_workflow.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    fixture_path.write_text(fixture_json, encoding="utf-8")

    print(f"Wrote {schema_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {fixture_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
