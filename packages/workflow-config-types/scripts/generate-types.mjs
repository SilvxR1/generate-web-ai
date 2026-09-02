// The Pydantic -> JSON Schema -> TS bridge: turns
// schema/workflow-config.schema.json (exported by
// apps/api/scripts/export_workflow_config_contract.py) into
// src/workflow-config.ts. Run manually after changing
// app.domain.workflow_config on the Python side — not wired into any
// build, so this package never needs Python present to type-check or be
// consumed. Mirrors business-config-types/scripts/generate-types.mjs
// exactly (same tool, same approach) rather than introducing a new one.
import { readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "json-schema-to-typescript";

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const schemaPath = join(packageRoot, "schema", "workflow-config.schema.json");
const outputPath = join(packageRoot, "src", "workflow-config.ts");

const schema = JSON.parse(await readFile(schemaPath, "utf-8"));

const ts = await compile(schema, "WorkflowConfig", {
  bannerComment:
    "/* eslint-disable */\n/**\n * Generated from apps/api's WorkflowConfig (Pydantic) via\n * apps/api/scripts/export_workflow_config_contract.py +\n * packages/workflow-config-types/scripts/generate-types.mjs.\n * Do not hand-edit — the Python model is the source of truth.\n */",
  additionalProperties: false,
  style: { singleQuote: false },
});

await writeFile(outputPath, ts);
console.log(`Wrote ${outputPath}`);
