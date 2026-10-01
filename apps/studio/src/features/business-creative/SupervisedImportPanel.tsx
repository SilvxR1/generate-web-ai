import { useCallback, useEffect, useState } from "react";
import { friendlyErrorMessage } from "../business-analysis/errors";
import {
  approveWebsiteDraft,
  buildSourceImport,
  decideSourceFinding,
  getSourceImport,
  getSourceImportCapability,
  getSourceImportDiagnostics,
  listSourceImports,
  previewWebsiteDraft,
  publishWebsiteDraft,
  reinspectSourceImport,
  runGenerativeVisualQa,
  uploadSourceImport,
  type SourceFinding,
  type SourceImport,
  type SourceImportCapability,
  type SourceImportSummary,
} from "../../lib/api";

/** Every call the panel makes — injectable so the panel is testable
 * without a server. Preview/approve/publish/Visual QA are the existing
 * website-draft endpoints: an imported site goes through the SAME
 * lifecycle (and the same exact-artifact gates) as every other draft. */
export interface SourceImportApi {
  capability: (businessId: string, tenantId: string) => Promise<SourceImportCapability>;
  list: (businessId: string, tenantId: string) => Promise<SourceImportSummary[]>;
  get: (businessId: string, importId: string, tenantId: string) => Promise<SourceImport>;
  diagnostics: (businessId: string, importId: string, tenantId: string) => Promise<unknown>;
  upload: (businessId: string, file: File, tenantId: string) => Promise<SourceImport>;
  decide: (
    businessId: string,
    importId: string,
    decision: { finding_id: string; decision: "approved" | "rejected"; rationale: string },
    tenantId: string,
  ) => Promise<SourceImport>;
  reinspect: (businessId: string, importId: string, tenantId: string) => Promise<SourceImport>;
  build: (businessId: string, importId: string, tenantId: string) => Promise<SourceImport>;
  visualQa: (businessId: string, draftId: string, tenantId: string) => Promise<unknown>;
  preview: (businessId: string, draftId: string, tenantId: string) => Promise<{ preview_url: string }>;
  approve: (businessId: string, draftId: string, tenantId: string) => Promise<unknown>;
  publish: (businessId: string, draftId: string, tenantId: string) => Promise<unknown>;
}

export const realSourceImportApi: SourceImportApi = {
  capability: getSourceImportCapability,
  list: listSourceImports,
  get: getSourceImport,
  diagnostics: getSourceImportDiagnostics,
  upload: uploadSourceImport,
  decide: decideSourceFinding,
  reinspect: reinspectSourceImport,
  build: buildSourceImport,
  visualQa: runGenerativeVisualQa,
  preview: previewWebsiteDraft,
  approve: approveWebsiteDraft,
  publish: publishWebsiteDraft,
};

/** The lifecycle, in order. Each import is at exactly one stage. */
export const STAGES: { key: string; label: string }[] = [
  { key: "imported", label: "Imported" },
  { key: "inspected", label: "Inspected" },
  { key: "review", label: "Source review" },
  { key: "building", label: "Building" },
  { key: "preview_ready", label: "Build/QA ready" },
  { key: "approved", label: "Artifact approved" },
  { key: "published", label: "Published" },
];

const STAGE_POSITION: Record<string, number> = {
  blocked: 1,
  stale: 1,
  needs_review: 2,
  rejected: 2,
  ready_to_build: 2,
  queued: 3,
  building: 3,
  build_failed: 3,
  preview_ready: 4,
  approved: 5,
  published: 6,
};

export const STAGE_LABELS: Record<string, string> = {
  blocked: "Blocked — a blocker must be fixed in the export or BusinessTruth",
  stale: "Stale — BusinessTruth changed; re-inspect",
  needs_review: "Needs review",
  rejected: "Rejected in review",
  ready_to_build: "Reviewed — ready to build",
  queued: "Build queued (waiting for the build worker)",
  building: "Building and validating on the build worker",
  build_failed: "Build or validation failed",
  preview_ready: "Preview ready — not approved yet",
  approved: "Artifact approved — ready to publish",
  published: "Published",
};

function short(sha: string | null | undefined): string {
  return sha ? sha.slice(0, 12) : "—";
}

function FindingRow({
  finding,
  canDecide,
  onDecide,
}: {
  finding: SourceFinding;
  canDecide: boolean;
  onDecide: (findingId: string, decision: "approved" | "rejected", rationale: string) => Promise<void>;
}) {
  const [rationale, setRationale] = useState("");
  const [busy, setBusy] = useState(false);
  const decide = (decision: "approved" | "rejected") => {
    setBusy(true);
    void onDecide(finding.id, decision, rationale).finally(() => setBusy(false));
  };
  return (
    <li className="source-import__finding" data-severity={finding.severity}>
      <strong>{finding.code}</strong> <span className="field-hint">{finding.subject}</span>
      <p className="field-hint">{finding.detail}</p>
      {finding.resolution && <p className="field-hint">Handled: {finding.resolution}</p>}
      {finding.approval && <p className="field-hint">Approved: {finding.approval}</p>}
      {canDecide && (
        <div className="source-import__decision">
          <label>
            Rationale (recorded with your name, this source and this plan)
            <textarea
              aria-label={`Rationale for ${finding.id}`}
              value={rationale}
              onChange={(event) => setRationale(event.target.value)}
            />
          </label>
          <button type="button" disabled={busy || !rationale.trim()} onClick={() => decide("approved")}>
            Approve finding
          </button>
          <button type="button" disabled={busy || !rationale.trim()} onClick={() => decide("rejected")}>
            Reject
          </button>
        </div>
      )}
    </li>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="source-import__section" aria-label={title}>
      <h5>{title}</h5>
      {children}
    </section>
  );
}

export interface DetailActions {
  decide: (findingId: string, decision: "approved" | "rejected", rationale: string) => Promise<void>;
  reinspect: () => Promise<void>;
  build: () => Promise<void>;
  visualQa: () => Promise<void>;
  preview: () => Promise<void>;
  approve: () => Promise<void>;
  publish: () => Promise<void>;
  diagnostics: () => Promise<unknown>;
}

export function SourceImportDetail({ item, actions }: { item: SourceImport; actions: DetailActions }) {
  const [diagnostics, setDiagnostics] = useState<string | null>(null);
  const inspection = item.inspection ?? {};
  const findings = inspection.findings ?? [];
  const blockers = findings.filter((f) => f.severity === "blocker" && f.open);
  const reviews = findings.filter((f) => f.severity === "review" && item.open_reviews.includes(f.id));
  const handled = findings.filter((f) => f.severity !== "info" && !f.open);
  const truthNotes = findings.filter((f) => f.severity === "info" && f.source === "facts");
  const position = STAGE_POSITION[item.stage] ?? 0;
  const draft = item.draft;
  const canBuild = item.status === "ready_to_build" || item.status === "build_failed";
  const launchBlockers = (inspection.readiness ?? []).filter((r) => r.severity === "launch_blocker");
  const framework = Object.entries(inspection.manifest?.framework?.dependencies ?? {})
    .map(([name, version]) => `${name} ${version}`)
    .join(", ");
  const qa = draft
    ? draft.visual_qa_current
      ? draft.visual_qa_passed
        ? "passed (this artifact)"
        : "failed"
      : "not run for this artifact"
    : "";

  return (
    <div className="source-import__detail">
      <ol className="source-import__stepper" aria-label="Lifecycle">
        {STAGES.map((stage, index) => (
          <li key={stage.key} aria-current={index === position ? "step" : undefined} data-done={index < position}>
            {stage.label}
          </li>
        ))}
      </ol>
      <p className="source-import__stage" role="status">
        {STAGE_LABELS[item.stage] ?? item.stage}
      </p>
      {item.error && <p className="banner banner--error">{item.error}</p>}

      <Section title="Source identity">
        <dl>
          <dt>File</dt>
          <dd>{item.original_filename}</dd>
          <dt>Source SHA-256</dt>
          <dd title={item.zip_sha256}>{short(item.zip_sha256)}</dd>
          <dt>Family / adapter</dt>
          <dd>
            {item.source_family ?? "not recognised"} · {item.adapter ?? "no adapter"}
          </dd>
          <dt>Framework</dt>
          <dd>{framework || "—"}</dd>
          <dt>Supportability</dt>
          <dd>{item.supportability ?? "—"}</dd>
          <dt>Plan</dt>
          <dd title={item.plan_sha256 ?? ""}>{short(item.plan_sha256)}</dd>
          <dt>BusinessTruth</dt>
          <dd>{item.business_truth_current ? "current" : "changed since inspection"}</dd>
          <dt>Site origin</dt>
          <dd>{item.site_origin}</dd>
        </dl>
      </Section>

      {blockers.length > 0 && (
        <Section title="Blockers (cannot be approved)">
          <ul>
            {blockers.map((f) => (
              <FindingRow key={f.id} finding={f} canDecide={false} onDecide={actions.decide} />
            ))}
          </ul>
        </Section>
      )}
      {reviews.length > 0 && (
        <Section title="Needs your review">
          <ul>
            {reviews.map((f) => (
              <FindingRow key={f.id} finding={f} canDecide={item.status === "needs_review"} onDecide={actions.decide} />
            ))}
          </ul>
        </Section>
      )}
      {item.decisions.length > 0 && (
        <Section title="Review decisions (this source and plan)">
          <ul>
            {item.decisions.map((d) => (
              <li key={`${d.finding_id}-${d.created_at}`}>
                {d.decision} · {d.finding_id} · {d.actor_email} · {new Date(d.created_at).toLocaleString()} —{" "}
                {d.rationale}
              </li>
            ))}
          </ul>
        </Section>
      )}
      {handled.length > 0 && (
        <Section title="Handled by the adapter">
          <ul>
            {handled.map((f) => (
              <FindingRow key={f.id} finding={f} canDecide={false} onDecide={actions.decide} />
            ))}
          </ul>
        </Section>
      )}

      <Section title="Security observations">
        {(inspection.security ?? []).length === 0 ? (
          <p className="field-hint">None.</p>
        ) : (
          <ul>
            {(inspection.security ?? []).map((s) => (
              <li key={`${s.code}-${s.path}-${s.detail}`}>
                {s.code} · {s.path} — {s.detail}
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Section title="BusinessTruth">
        <ul>
          {(inspection.fact_bindings ?? []).map((b) => (
            <li key={b.field}>
              {b.field}: {b.changes_text ? `"${b.literal}" → "${b.value}"` : `"${b.value}" (matches)`}
            </li>
          ))}
          {truthNotes.map((f) => (
            <li key={f.id} className="field-hint">
              {f.detail}
            </li>
          ))}
        </ul>
      </Section>
      <Section title="External origins">
        <ul>
          {(inspection.external_origins ?? [])
            .filter((o) => o.client_live)
            .map((o) => (
              <li key={`${o.origin}-${o.context}`}>
                {o.origin} ({o.context})
              </li>
            ))}
        </ul>
      </Section>
      <Section title="Forms">
        {(inspection.forms ?? []).map((form) => (
          <ul key={form.form_id} aria-label={`Form ${form.form_id}`}>
            {form.fields.map((field) => (
              <li key={field.name}>
                {field.label} ({field.name}) → {field.role}
                {field.required ? " · required" : ""}
              </li>
            ))}
          </ul>
        ))}
      </Section>
      {inspection.build && (
        <Section title="Build requirements">
          <p>
            Toolchain: {inspection.build.toolchain}. Steps:{" "}
            {inspection.build.sandbox_steps.map((s) => s.argv.join(" ")).join(" → ")}
          </p>
          <p>Pages: {inspection.build.expected_pages.join(", ")}</p>
        </Section>
      )}
      {inspection.plan && (
        <Section title="Adaptation plan">
          <p>
            {inspection.plan.operations} operations on {inspection.plan.files_changed} files:{" "}
            {Object.entries(inspection.plan.by_category)
              .map(([category, count]) => `${category} ${count}`)
              .join(", ")}
          </p>
          <ul>
            {inspection.plan.visible.map((v) => (
              <li key={v.op}>Visible change: {v.visible}</li>
            ))}
          </ul>
        </Section>
      )}
      {launchBlockers.length > 0 && (
        <Section title="Outstanding launch blockers (owner/legal)">
          <ul>
            {launchBlockers.map((r) => (
              <li key={`${r.code}-${r.detail}`}>{r.detail}</li>
            ))}
          </ul>
        </Section>
      )}

      <div className="source-import__actions">
        <button type="button" onClick={() => void actions.reinspect()}>
          Re-inspect
        </button>
        <button type="button" disabled={!canBuild} onClick={() => void actions.build()}>
          Build on the build worker
        </button>
      </div>

      {draft && (
        <Section title="Artifact">
          <dl>
            <dt>Artifact SHA-256</dt>
            <dd title={draft.artifact_sha256 ?? ""}>{short(draft.artifact_sha256)}</dd>
            <dt>Visual QA</dt>
            <dd>{qa}</dd>
            <dt>Approved artifact</dt>
            <dd>{short(draft.approved_artifact_sha256)}</dd>
          </dl>
          {draft.build_error && <p className="banner banner--error">{draft.build_error}</p>}
          {draft.gate_problems.map((problem) => (
            <p key={problem} className="banner banner--warning">
              {problem}
            </p>
          ))}
          <div className="source-import__actions">
            <button type="button" disabled={draft.status !== "ready"} onClick={() => void actions.visualQa()}>
              Run Visual QA
            </button>
            <button
              type="button"
              disabled={draft.status !== "ready" && draft.status !== "approved"}
              onClick={() => void actions.preview()}
            >
              Preview (does not approve)
            </button>
            <button
              type="button"
              disabled={draft.status !== "ready" || draft.gate_problems.length > 0}
              onClick={() => void actions.approve()}
            >
              Approve this artifact
            </button>
            <button type="button" disabled={draft.status !== "approved"} onClick={() => void actions.publish()}>
              Publish approved artifact
            </button>
          </div>
          {draft.preview_url && (
            <p>
              Preview:{" "}
              <a href={draft.preview_url} target="_blank" rel="noopener noreferrer">
                {draft.preview_url}
              </a>
            </p>
          )}
          <p className="field-hint">Previous versions and rollback are in the Website section.</p>
        </Section>
      )}

      <details
        onToggle={(event) => {
          if ((event.target as HTMLDetailsElement).open && diagnostics === null) {
            actions
              .diagnostics()
              .then((data) => setDiagnostics(JSON.stringify(data, null, 2)))
              .catch(() => setDiagnostics("Diagnostics are unavailable."));
          }
        }}
      >
        <summary>Diagnostics (raw manifest and plan)</summary>
        <pre className="source-import__raw">{diagnostics ?? "Loading…"}</pre>
      </details>
    </div>
  );
}

/** R5 — supervised import of a website exported from Higgsfield after the
 * owner reviewed it. GWA does NOT generate or fetch anything from
 * Higgsfield: the operator uploads the ZIP; GWA inspects, asks for review,
 * builds on its isolated build worker and validates; then the normal
 * preview -> approve -> publish -> rollback lifecycle applies. */
export function SupervisedImportPanel({
  businessId,
  tenantId,
  api = realSourceImportApi,
}: {
  businessId: string;
  tenantId: string;
  api?: SourceImportApi;
}) {
  const [capability, setCapability] = useState<SourceImportCapability | null>(null);
  const [items, setItems] = useState<SourceImportSummary[]>([]);
  const [selected, setSelected] = useState<SourceImport | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refreshList = useCallback(() => api.list(businessId, tenantId).then(setItems), [api, businessId, tenantId]);

  useEffect(() => {
    api
      .capability(businessId, tenantId)
      .then((cap) => {
        setCapability(cap);
        return cap.enabled ? refreshList() : undefined;
      })
      .catch((cause: unknown) => setError(friendlyErrorMessage(cause, "Could not load supervised imports.")));
  }, [api, businessId, tenantId, refreshList]);

  const run = async (task: () => Promise<unknown>, fallback: string): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      await task();
    } catch (cause) {
      setError(friendlyErrorMessage(cause, fallback));
    } finally {
      setBusy(false);
    }
  };

  const reload = (importId: string) =>
    api.get(businessId, importId, tenantId).then((item) => {
      setSelected(item);
      return refreshList();
    });

  if (capability === null) {
    return error ? <p className="banner banner--error">{error}</p> : <p className="field-hint">Loading…</p>;
  }
  if (!capability.enabled) {
    return <p className="field-hint">Supervised website imports are not enabled on this server.</p>;
  }

  const id = selected?.id;
  const draftId = String(selected?.draft?.id ?? "");
  const actions: DetailActions | null = id
    ? {
        decide: (findingId, decision, rationale) =>
          run(
            () => api.decide(businessId, id, { finding_id: findingId, decision, rationale }, tenantId).then(setSelected),
            "The decision could not be recorded.",
          ),
        reinspect: () => run(() => api.reinspect(businessId, id, tenantId).then(setSelected), "Re-inspection failed."),
        build: () => run(() => api.build(businessId, id, tenantId).then(setSelected), "The build could not start."),
        visualQa: () => run(() => api.visualQa(businessId, draftId, tenantId).then(() => reload(id)), "Visual QA failed to run."),
        preview: () =>
          run(
            () =>
              api.preview(businessId, draftId, tenantId).then((preview) => {
                window.open(preview.preview_url, "_blank", "noopener,noreferrer");
                return reload(id);
              }),
            "The preview could not be prepared.",
          ),
        approve: () => run(() => api.approve(businessId, draftId, tenantId).then(() => reload(id)), "Approval failed."),
        publish: () => run(() => api.publish(businessId, draftId, tenantId).then(() => reload(id)), "Publishing failed."),
        diagnostics: () => api.diagnostics(businessId, id, tenantId),
      }
    : null;

  return (
    <div className="source-import">
      <p className="field-hint">
        Supervised import: upload a website ZIP exported from Higgsfield after the owner reviewed it. GWA does not
        generate sites with Higgsfield and never contacts Higgsfield — it inspects the export, asks you to review
        anything it can't decide, builds it on the isolated build worker, validates it and lets you preview, approve
        and publish the exact result.
      </p>
      {capability.access === "scoped" && (
        <p className="banner banner--warning">
          Canary access: supervised imports are enabled for this business only, while the feature stays off for
          everyone else.
        </p>
      )}
      {!capability.worker_configured && (
        <p className="banner banner--warning">No build worker is configured: you can import and review, not build.</p>
      )}
      {error && <p className="banner banner--error">{error}</p>}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!file) return;
          void run(
            () =>
              api.upload(businessId, file, tenantId).then((item) => {
                setSelected(item);
                return refreshList();
              }),
            "The import failed.",
          );
        }}
      >
        <label>
          Export ZIP (max {Math.round(capability.max_bytes / 1024 / 1024)} MB)
          <input
            type="file"
            accept=".zip,application/zip"
            aria-label="Export ZIP"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <button type="submit" disabled={!file || busy}>
          Import and inspect
        </button>
      </form>

      {items.length > 0 && (
        <ul className="source-import__list" aria-label="Imports">
          {items.map((item) => (
            <li key={item.id}>
              <button type="button" onClick={() => void run(() => reload(item.id), "Could not load the import.")}>
                {item.original_filename} · {short(item.zip_sha256)} · {STAGE_LABELS[item.stage] ?? item.stage}
              </button>
            </li>
          ))}
        </ul>
      )}

      {selected && actions && <SourceImportDetail item={selected} actions={actions} />}
    </div>
  );
}
