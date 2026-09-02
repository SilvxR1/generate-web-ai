# @generate-web-ai/workflow-config-types

TypeScript types for `WorkflowConfig`, generated from `apps/api`'s
Pydantic model — the same minimal Pydantic → JSON Schema → TS bridge
`@generate-web-ai/business-config-types` already uses, applied to the
workflow side instead of a second, hand-maintained TypeScript
`WorkflowConfig` definition (which is exactly what existed before this
package — apps/studio's own hand-mirrored types — and had already
drifted from the real Python shape).

```
apps/api/app/domain/workflow_config/  (Pydantic — source of truth)
        ↓  apps/api/scripts/export_workflow_config_contract.py
schema/workflow-config.schema.json + fixtures/reforma-valencia-lead-capture.json
        ↓  scripts/generate-types.mjs  (json-schema-to-typescript)
src/workflow-config.ts  (generated — do not hand-edit)
```

## Regenerating

After any change to `apps/api/app/domain/workflow_config/`:

```sh
cd apps/api && uv run python scripts/export_workflow_config_contract.py
cd packages/workflow-config-types && node scripts/generate-types.mjs
```

Both the exported schema/fixture JSON and the generated `.ts` are
committed — this package never needs Python present to type-check or be
consumed by `apps/studio`; regeneration is a manual, explicit step (not
wired into `pnpm build`), matching `@generate-web-ai/business-config-types`'s
own "minimal tooling" instruction.

## Deliberately not included

Runtime validation (no zod/ajv schema compiled from the JSON Schema) —
this package is types only, same boundary as
`@generate-web-ai/business-config-types`.
