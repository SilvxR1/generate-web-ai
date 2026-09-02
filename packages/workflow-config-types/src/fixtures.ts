// Same fixture apps/api's Python tests exercise
// (generate_lead_capture_workflow(EXAMPLE_REFORMA_VALENCIA_CONFIG)),
// exported straight from the JSON apps/api/scripts/export_workflow_config_contract.py
// wrote — not hand-duplicated here. Mirrors business-config-types'
// own exampleReformaValenciaConfig fixture export.
import type { WorkflowConfig } from "./workflow-config.ts";
import reformaValenciaWorkflowJson from "../fixtures/reforma-valencia-lead-capture.json";

// Trusted, not re-validated here (see this package's README): the JSON
// was produced by WorkflowConfig.model_dump() on the Python side, which
// already validated it.
export const exampleReformaValenciaLeadCaptureWorkflow = reformaValenciaWorkflowJson as unknown as WorkflowConfig;
