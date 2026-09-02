import { useState } from "react";
import { useOutletContext } from "react-router-dom";
import { BriefingForm } from "../features/business-analysis/BriefingForm";
import { ErrorBanner } from "../features/business-analysis/ErrorBanner";
import { buildCreatePayload, buildDraftFromAnalysis, validateDraft, type BusinessDraft } from "../features/business-analysis/draft";
import { categorizeAnalyzeError, categorizeSaveError, type CategorizedError } from "../features/business-analysis/errors";
import { ProposalReview } from "../features/business-analysis/ProposalReview";
import { PreviewStep } from "../features/business-preview/PreviewStep";
import { analyzeBusiness, createBusiness, updateBusiness, type AnalyzeBusinessResponse, type CreatedBusiness } from "../lib/api";
import type { TenantOutletContext } from "../layout/AppShell";

type Step =
  | { kind: "briefing"; isAnalyzing: boolean }
  | { kind: "reviewing"; analysis: AnalyzeBusinessResponse; draft: BusinessDraft; editingBusiness: CreatedBusiness | null }
  | { kind: "preview"; business: CreatedBusiness };

export function NewBusiness() {
  const { tenantId } = useOutletContext<TenantOutletContext>();
  const [step, setStep] = useState<Step>({ kind: "briefing", isAnalyzing: false });
  const [analyzeError, setAnalyzeError] = useState<CategorizedError | null>(null);
  const [saveError, setSaveError] = useState<CategorizedError | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  async function handleAnalyze(briefing: string) {
    setAnalyzeError(null);
    setStep({ kind: "briefing", isAnalyzing: true });
    try {
      // Analysis only ever proposes a config for a human to review — see
      // POST /businesses/analyze's own docstring (apps/api). Nothing is
      // persisted by this call.
      const analysis = await analyzeBusiness(briefing, tenantId);
      setStep({ kind: "reviewing", analysis, draft: buildDraftFromAnalysis(analysis, briefing), editingBusiness: null });
    } catch (error) {
      setAnalyzeError(categorizeAnalyzeError(error));
      setStep({ kind: "briefing", isAnalyzing: false });
    }
  }

  async function handleSave(draft: BusinessDraft, editingBusiness: CreatedBusiness | null) {
    const validationErrors = validateDraft(draft);
    if (validationErrors.length > 0) {
      setSaveError({ category: "invalid_proposal", title: "Fix the proposal first", message: validationErrors.join(" ") });
      return;
    }
    setSaveError(null);
    setIsSaving(true);
    try {
      const payload = buildCreatePayload(draft);
      const business = editingBusiness
        ? await updateBusiness(editingBusiness.id, payload, tenantId)
        : await createBusiness(payload, tenantId);
      setStep({ kind: "preview", business });
    } catch (error) {
      setSaveError(categorizeSaveError(error));
    } finally {
      setIsSaving(false);
    }
  }

  if (!tenantId) {
    return (
      <section>
        <h1>New Business</h1>
        <p className="banner banner--warning">Set a Tenant ID above before creating a business.</p>
      </section>
    );
  }

  return (
    <section>
      <h1>New Business</h1>

      {step.kind === "briefing" && (
        <>
          {analyzeError && <ErrorBanner error={analyzeError} />}
          <BriefingForm onSubmit={handleAnalyze} isSubmitting={step.isAnalyzing} />
        </>
      )}

      {step.kind === "reviewing" && (
        <ProposalReview
          analysis={step.analysis}
          draft={step.draft}
          onChange={(updater) =>
            setStep((prev) => (prev.kind === "reviewing" ? { ...prev, draft: updater(prev.draft) } : prev))
          }
          tenantId={tenantId}
          isEditingExisting={step.editingBusiness !== null}
          onBack={() => {
            setSaveError(null);
            setStep(
              step.editingBusiness ? { kind: "preview", business: step.editingBusiness } : { kind: "briefing", isAnalyzing: false },
            );
          }}
          onCreate={() => handleSave(step.draft, step.editingBusiness)}
          isCreating={isSaving}
          createError={saveError}
          submitLabel={step.editingBusiness ? "Save changes" : "Create business"}
        />
      )}

      {step.kind === "preview" && (
        <PreviewStep
          business={step.business}
          tenantId={tenantId}
          onEdit={() => {
            setSaveError(null);
            const analysis: AnalyzeBusinessResponse = {
              proposed_config: step.business.config,
              missing_information: [],
              questions: [],
            };
            setStep({
              kind: "reviewing",
              analysis,
              draft: buildDraftFromAnalysis(analysis, step.business.raw_description),
              editingBusiness: step.business,
            });
          }}
          onCreateAnother={() => setStep({ kind: "briefing", isAnalyzing: false })}
        />
      )}
    </section>
  );
}
