"""Exports the BusinessConfig contract for the TypeScript side to consume
— the minimal Pydantic -> JSON Schema -> TS-types bridge (see
packages/business-config-types/README.md) rather than a second,
hand-maintained TypeScript BusinessConfig definition.

Writes:
  packages/business-config-types/schema/business-config.schema.json
  packages/business-config-types/fixtures/reforma-valencia.json

Run after any change to app.domain.business_config, then regenerate the
TypeScript types (see that package's README) — this is a manual,
explicit step, not wired into any build, so the JS side never needs
Python present to build.
"""

import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))  # so `uv run python scripts/...` works without a separate PYTHONPATH

from app.domain.business_config import EXAMPLE_REFORMA_VALENCIA_CONFIG, BusinessConfig  # noqa: E402

REPO_ROOT = API_ROOT.parent.parent
OUTPUT_PACKAGE = REPO_ROOT / "packages" / "business-config-types"


def _strip_titles(node: object, parent_key: str | None = None) -> object:
    """Pydantic auto-generates a `title` (e.g. "Alt", "Url") for every
    field from its name — noise, not meaningful documentation. Left in,
    json-schema-to-typescript hoists each into its own single-field type
    alias on the TS side, which is exactly the "second schema, not
    generated" clutter this bridge exists to avoid. Docstrings
    (`description`) are kept; only the redundant per-field titles go.

    `parent_key` tracks whether the current dict is a "properties" (or
    "$defs") map — there, keys are field/class *names*, not JSON Schema
    metadata, so a field that happens to be named "title" (e.g.
    SEOPreferences.title) must never be dropped just because it matches
    the metadata keyword's spelling. Only `title` keys that are actual
    schema-node metadata (siblings of "type"/"$ref"/...) get stripped.
    """
    if isinstance(node, dict):
        if parent_key in ("properties", "$defs"):
            return {key: _strip_titles(value) for key, value in node.items()}
        return {key: _strip_titles(value, parent_key=key) for key, value in node.items() if key != "title"}
    if isinstance(node, list):
        return [_strip_titles(item) for item in node]
    return node


def main() -> None:
    schema_path = OUTPUT_PACKAGE / "schema" / "business-config.schema.json"
    fixture_path = OUTPUT_PACKAGE / "fixtures" / "reforma-valencia.json"
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.parent.mkdir(parents=True, exist_ok=True)

    schema = _strip_titles(BusinessConfig.model_json_schema())
    schema_path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    fixture = EXAMPLE_REFORMA_VALENCIA_CONFIG.model_dump(mode="json")
    fixture_path.write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"Wrote {schema_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {fixture_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
