/* eslint-disable */
/**
 * Generated from apps/api's WorkflowConfig (Pydantic) via
 * apps/api/scripts/export_workflow_config_contract.py +
 * packages/workflow-config-types/scripts/generate-types.mjs.
 * Do not hand-edit — the Python model is the source of truth.
 */

export type ActionType =
  "lead.store" | "lead.lookup" | "lead.follow_up_email" | "email.send" | "notification.send" | "http.request" | "wait";
/**
 * A role, never a literal address — the future AutomationEngine
 * resolves this against the triggering event/business, not this
 * config.
 */
export type EmailRecipient = "customer" | "business_owner";
export type ConditionOperator = "equals" | "contains" | "exists";

export interface WorkflowConfig {
  connections?: WorkflowConnection[];
  error_handling?: ErrorHandlingConfig;
  id: string;
  name: string;
  nodes?: (ActionNode | ConditionNode)[];
  /**
   * Always derived from `nodes`, never hand-supplied — there is no
   * way for this to drift from what the workflow actually needs.
   */
  required_capabilities: string[];
  trigger: LeadSubmittedTrigger | WebhookTrigger;
  version?: number;
}
/**
 * One edge in the workflow's node graph. `source` is either the
 * literal string "trigger" (the workflow's single entry point) or a
 * node id; `source_output` names which of that node's declared
 * `outputs` this edge follows (a `condition` node has "true"/"false";
 * most `action` nodes just have "done"). Referential integrity
 * (source/target actually exist, source_output actually exists on that
 * node) is enforced at the WorkflowConfig level, where the full node
 * list is known — see workflow.py.
 */
export interface WorkflowConnection {
  source: string;
  source_output?: string;
  target: string;
}
export interface ErrorHandlingConfig {
  max_retries?: number;
  notify_on_failure?: boolean;
  strategy?: "stop" | "continue" | "retry";
}
export interface ActionNode {
  action: ActionType;
  id: string;
  inputs:
    | LeadStoreInputs
    | LeadLookupInputs
    | LeadFollowUpEmailInputs
    | EmailSendInputs
    | NotificationSendInputs
    | HttpRequestInputs
    | WaitInputs;
  /**
   * @minItems 1
   */
  outputs?: [string, ...string[]];
  type?: "action";
}
export interface LeadStoreInputs {
  action?: "lead.store";
}
/**
 * Fetches one lead's *current* state — the fresh read a follow-up
 * condition needs after a wait, as opposed to whatever data was known
 * when the lead was first stored. Same minimal shape as
 * LeadStoreInputs (no fields beyond the discriminator): which lead and
 * which tenant/business is runtime data (the id lead.store returned,
 * resolved by the future AutomationEngine/translator), never something
 * this config carries.
 */
export interface LeadLookupInputs {
  action?: "lead.lookup";
}
/**
 * Sends a real, provider-neutral email *to the lead itself* — never
 * represented as an InternalNotification (that model means "the
 * business's own team was told about something", a different concept
 * this action deliberately stays clear of). No recipient here: it's
 * resolved server-side from the lead's own current row (see
 * app.routers.internal_automation's follow-up-email endpoint), the
 * same "runtime data, not config" reasoning as LeadLookupInputs above.
 * `template` mirrors NotificationSendInputs.template — a named id,
 * unused by the translator today (content is a fixed, safe, business-
 * name-based message for this MVP; no per-template dynamic generation
 * yet), kept for the same forward-compatibility reason.
 */
export interface LeadFollowUpEmailInputs {
  action?: "lead.follow_up_email";
  template: string;
}
export interface EmailSendInputs {
  action?: "email.send";
  subject?: string | null;
  template: string;
  to: EmailRecipient;
}
export interface NotificationSendInputs {
  action?: "notification.send";
  template: string;
}
export interface HttpRequestInputs {
  action?: "http.request";
  body_template?: string | null;
  headers?: {
    [k: string]: string;
  };
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  url: string;
}
/**
 * Pauses the workflow for a fixed duration before continuing —
 * e.g. the gap between "notify the business" and "check whether the
 * lead was contacted yet" in a follow-up sequence. A plain delay only:
 * no "resume on webhook"/"resume at specific time" mode, since nothing
 * in this codebase needs those yet.
 */
export interface WaitInputs {
  action?: "wait";
  hours: number;
}
export interface ConditionNode {
  condition: NodeCondition;
  id: string;
  /**
   * @minItems 1
   */
  outputs?: [string, ...string[]];
  type?: "condition";
}
/**
 * `field` is a dotted path into the triggering event's payload
 * (e.g. "lead.email") — resolved by the future AutomationEngine, not
 * interpreted here.
 */
export interface NodeCondition {
  field: string;
  operator: ConditionOperator;
  value?: string | number | boolean | null;
}
/**
 * Fires on the website's `lead.submitted` DOM event (see
 * packages/blocks/Contact.astro) — no config needed, it's an internal,
 * already-neutral signal.
 */
export interface LeadSubmittedTrigger {
  type?: "lead.submitted";
}
export interface WebhookTrigger {
  method?: "GET" | "POST";
  path: string;
  type?: "webhook";
}
