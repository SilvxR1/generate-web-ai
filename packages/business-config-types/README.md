# @generate-web-ai/business-config-types

TypeScript types for `BusinessConfig`, generated from `apps/api`'s
Pydantic model — the minimal Pydantic → JSON Schema → TS bridge, chosen
specifically to avoid maintaining a second, hand-written TypeScript
`BusinessConfig` definition that could drift from the real (Python)
source of truth.

```
apps/api/app/domain/business_config/  (Pydantic — source of truth)
        ↓  apps/api/scripts/export_business_config_contract.py
schema/business-config.schema.json + fixtures/reforma-valencia.json
        ↓  scripts/generate-types.mjs  (json-schema-to-typescript)
src/business-config.ts  (generated — do not hand-edit)
```

## Regenerating

After any change to `apps/api/app/domain/business_config/`:

```sh
cd apps/api && uv run python scripts/export_business_config_contract.py
cd packages/business-config-types && node scripts/generate-types.mjs
```

Both the exported schema/fixture JSON and the generated `.ts` are
committed — this package never needs Python present to type-check or be
consumed by `@generate-web-ai/website-generator`; regeneration is a
manual, explicit step (not wired into `pnpm build`), matching the
"minimal tooling" instruction it was built under.

## Deliberately not included

Runtime validation (e.g. no zod/ajv schema compiled from the JSON
Schema) — this package is types only. Anything consuming
`fixtures/reforma-valencia.json` at runtime should treat it as already
trusted (it comes from the same Pydantic model that validated it on the
Python side), not re-validate it here.
