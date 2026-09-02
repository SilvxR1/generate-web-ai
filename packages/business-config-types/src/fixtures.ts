// Same fixture apps/api's Python tests exercise (EXAMPLE_REFORMA_VALENCIA_CONFIG),
// exported straight from the JSON apps/api/scripts/export_business_config_contract.py
// wrote — not hand-duplicated here. Mirrors packages/site-config's own
// exampleSiteConfig export.
import type { BusinessConfig } from "./business-config.ts";
import reformaValenciaJson from "../fixtures/reforma-valencia.json";

// Trusted, not re-validated here (see this package's README): the JSON
// was produced by BusinessConfig.model_dump() on the Python side, which
// already validated it. TS's structural checker can't see through the
// JSON import's inferred literal types (e.g. `days: string[]` vs the
// `[Weekday, ...Weekday[]]` tuple), hence the `unknown` step.
export const exampleReformaValenciaConfig = reformaValenciaJson as unknown as BusinessConfig;
