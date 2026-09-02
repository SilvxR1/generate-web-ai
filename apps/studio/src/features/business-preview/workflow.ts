import type { WorkflowConfig } from "@generate-web-ai/workflow-config-types";

// Derived from the generated WorkflowConfig itself (never a second,
// hand-written union) so a new node/trigger variant added on the Python
// side is automatically reflected here.
type WorkflowNode = NonNullable<WorkflowConfig["nodes"]>[number];
type WorkflowTrigger = WorkflowConfig["trigger"];

export function describeTrigger(trigger: WorkflowTrigger): string {
  switch (trigger.type) {
    case "lead.submitted":
      return "Lead submitted";
    case "webhook":
      return `Webhook (${trigger.method ?? "POST"} ${trigger.path ?? ""})`;
    default:
      // `type` is optional in the generated types (Pydantic never lists
      // a field with a default as "required" in its JSON Schema, even
      // though a real response always includes it) — this only fires on
      // a genuinely unrecognized/missing trigger shape.
      return "Unknown trigger";
  }
}

export function describeNode(node: WorkflowNode): string {
  if ("condition" in node) {
    const { field, operator, value } = node.condition;
    return `If ${field} ${operator}${value !== undefined && value !== null ? ` ${String(value)}` : ""}`;
  }
  switch (node.action) {
    case "lead.store":
      return "Store lead";
    case "notification.send": {
      const inputs = node.inputs;
      // Distinguishes the two real notification.send nodes a follow-up
      // workflow has (notify-internal vs notify-follow-up) — both share
      // this one action type, so without reading `template` they'd
      // render as the same indistinguishable "Notify" label twice.
      return inputs.action === "notification.send" && inputs.template === "lead_follow_up"
        ? "Follow-up notification"
        : "Notify";
    }
    case "email.send": {
      const inputs = node.inputs;
      return inputs.action === "email.send" && inputs.to === "customer" ? "Customer email" : "Team email";
    }
    case "http.request":
      return "Call external service";
    case "wait": {
      const inputs = node.inputs;
      return inputs.action === "wait" ? `Wait ${inputs.hours}h` : "Wait";
    }
    case "lead.lookup":
      return "Check lead status";
    default:
      // Every action the real generator emits is handled above — this
      // only fires for a genuinely unrecognized node, so it still gets
      // a readable label instead of a raw id like "store-lead".
      return humanizeId(node.id);
  }
}

function humanizeId(id: string): string {
  return id
    .split(/[-_]/)
    .filter(Boolean)
    .map((word) => word[0]!.toUpperCase() + word.slice(1))
    .join(" ");
}

// The action ids a WorkflowConfig's required_capabilities lists
// (app.domain.workflow_config.actions.ActionType) — shown to the user as
// plain-language capability names, never the raw dotted id.
// Deliberately phrased differently from describeNode's diagram labels
// (e.g. "Store the lead" vs. the diagram's "Store lead") — this list
// describes required capabilities overall, not a specific step, and the
// two shouldn't render as literal duplicate text on the same screen.
const CAPABILITY_LABELS: Record<string, string> = {
  "lead.store": "Store the lead",
  "lead.lookup": "Look up the lead",
  "lead.follow_up_email": "Send a follow-up email",
  "email.send": "Send an email",
  "notification.send": "Send a notification",
  "http.request": "Call an external service",
  wait: "Wait before continuing",
};

export function describeCapability(capability: string): string {
  return CAPABILITY_LABELS[capability] ?? humanizeId(capability.replace(/\./g, "-"));
}

/** "Enabled — waits Xh, then checks..." or "Disabled" — derived purely
 * from whether the real generated workflow contains a `wait` node
 * (app.domain.workflow_config.generator only adds one when
 * automation.follow_up.enabled), never a separate flag this dashboard
 * tracks on its own. So this can never say "enabled" for a workflow
 * that wouldn't actually wait, or vice versa. */
export function describeFollowUp(workflow: WorkflowConfig): string {
  for (const node of workflow.nodes ?? []) {
    if ("condition" in node) continue;
    if (node.action === "wait" && node.inputs.action === "wait") {
      return `Enabled — waits ${node.inputs.hours}h, then checks if the lead is still new before following up`;
    }
  }
  return "Disabled";
}

export interface DiagramBox {
  id: string;
  label: string;
}

/** Lays the workflow's real node graph out as simple top-to-bottom rows —
 * trigger first, then each BFS layer of its connections — so the diagram
 * always reflects whatever WorkflowConfig the backend actually generated,
 * not a hardcoded picture of the one lead-capture shape that exists today. */
export function layerWorkflow(workflow: WorkflowConfig): DiagramBox[][] {
  const nodes = workflow.nodes ?? [];
  const connections = workflow.connections ?? [];
  const nodesById = new Map(nodes.map((node) => [node.id, node]));
  const childrenOf = new Map<string, string[]>();
  for (const connection of connections) {
    const children = childrenOf.get(connection.source) ?? [];
    children.push(connection.target);
    childrenOf.set(connection.source, children);
  }

  const layers: DiagramBox[][] = [[{ id: "trigger", label: describeTrigger(workflow.trigger) }]];
  const visited = new Set<string>(["trigger"]);
  let frontier = childrenOf.get("trigger") ?? [];
  let guard = 0;

  while (frontier.length > 0 && guard < 100) {
    guard += 1;
    const layer: DiagramBox[] = [];
    const next: string[] = [];
    for (const id of frontier) {
      if (visited.has(id)) continue;
      visited.add(id);
      const node = nodesById.get(id);
      if (!node) continue;
      layer.push({ id, label: describeNode(node) });
      for (const childId of childrenOf.get(id) ?? []) {
        if (!visited.has(childId)) next.push(childId);
      }
    }
    if (layer.length > 0) layers.push(layer);
    frontier = next;
  }

  return layers;
}
