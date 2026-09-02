// Drift guard for src/workflow-config.ts: re-runs the exact same
// json-schema-to-typescript compile() generate-types.mjs performs and
// asserts the checked-in file is byte-identical to what it produces
// right now. If this fails, the schema changed (see apps/api's
// test_workflow_config_contract_export.py for that half of the check)
// but `node scripts/generate-types.mjs` was never re-run.
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "json-schema-to-typescript";
import { describe, expect, it } from "vitest";

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const schemaPath = join(packageRoot, "schema", "workflow-config.schema.json");
const outputPath = join(packageRoot, "src", "workflow-config.ts");

describe("workflow-config.ts", () => {
  it("matches what compiling the checked-in schema produces right now", async () => {
    const schema = JSON.parse(await readFile(schemaPath, "utf-8"));

    const regenerated = await compile(schema, "WorkflowConfig", {
      bannerComment:
        "/* eslint-disable */\n/**\n * Generated from apps/api's WorkflowConfig (Pydantic) via\n * apps/api/scripts/export_workflow_config_contract.py +\n * packages/workflow-config-types/scripts/generate-types.mjs.\n * Do not hand-edit — the Python model is the source of truth.\n */",
      additionalProperties: false,
      style: { singleQuote: false },
    });

    const committed = await readFile(outputPath, "utf-8");

    expect(regenerated).toBe(committed);
  });
});
