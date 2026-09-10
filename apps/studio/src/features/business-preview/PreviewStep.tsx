import { generateSiteConfig } from "@generate-web-ai/website-generator";
import type { WorkflowConfig } from "@generate-web-ai/workflow-config-types";
import { useEffect, useMemo, useState } from "react";
import { categorizeWorkflowPreviewError, friendlyErrorMessage } from "../business-analysis/errors";
import type { CategorizedError } from "../business-analysis/errors";
import {
  activateAutomation,
  attachCustomDomain,
  checkWebsiteHealthNow,
  deactivateAutomation,
  detachCustomDomain,
  getAutomationState,
  getBusinessMetrics,
  getCustomDomain,
  getLeads,
  getProductionReadiness,
  getWebsiteHealth,
  getWebsiteState,
  getWebsiteVersions,
  getWorkflowPreview,
  listBusinessAssets,
  publishWebsite,
  refreshCustomDomain,
  rollbackToWebsiteVersion,
  updateLeadStatus,
  type AutomationState,
  type BusinessAsset,
  type BusinessMetrics,
  type CreatedBusiness,
  type CustomDomainState,
  type Lead,
  type LeadFilters,
  type LeadStatus,
  type MetricsWindow,
  type ProductionReadinessReport,
  type WebsiteHealth,
  type WebsiteState,
  type WebsiteVersionSummary,
} from "../../lib/api";
import { BusinessMetricsPanel } from "./BusinessMetricsPanel";
import { CreativeSection } from "../business-creative/CreativeSection";
import { CustomDomainPanel } from "./CustomDomainPanel";
import { LeadsList } from "./LeadsList";
import { ProductionReadinessPanel } from "./ProductionReadinessPanel";
import { SiteConfigPreview } from "./SiteConfigPreview";
import { WebsiteHealthPanel } from "./WebsiteHealthPanel";
import { WebsitePublish } from "./WebsitePublish";
import { WebsiteVersionsPanel } from "./WebsiteVersionsPanel";
import { WorkflowPreview } from "./WorkflowPreview";

interface PreviewStepProps {
  business: CreatedBusiness;
  tenantId: string;
  onEdit: () => void;
  onCreateAnother: () => void;
}

interface WorkflowPreviewState {
  workflow: WorkflowConfig | null;
  isLoading: boolean;
  error: CategorizedError | null;
}

interface AutomationStateFetch {
  state: AutomationState | null;
  isLoading: boolean;
}

interface WebsiteStateFetch {
  state: WebsiteState | null;
  isLoading: boolean;
}

interface CustomDomainFetch {
  state: CustomDomainState | null;
  isLoading: boolean;
}

interface WebsiteVersionsFetch {
  versions: WebsiteVersionSummary[] | null;
  isLoading: boolean;
}

interface ProductionReadinessFetch {
  report: ProductionReadinessReport | null;
  isLoading: boolean;
}

interface LeadsFetch {
  leads: Lead[] | null;
  isLoading: boolean;
  error: string | null;
}

interface WebsiteHealthFetch {
  health: WebsiteHealth | null;
  isLoading: boolean;
}

interface BusinessMetricsFetch {
  metrics: BusinessMetrics | null;
  isLoading: boolean;
}

interface BusinessAssetsFetch {
  assets: BusinessAsset[] | null;
  isLoading: boolean;
}

export function PreviewStep({ business, tenantId, onEdit, onCreateAnother }: PreviewStepProps) {
  const [workflowState, setWorkflowState] = useState<WorkflowPreviewState>({
    workflow: null,
    isLoading: true,
    error: null,
  });
  const [automation, setAutomation] = useState<AutomationStateFetch>({ state: null, isLoading: true });
  const [website, setWebsite] = useState<WebsiteStateFetch>({ state: null, isLoading: true });
  const [customDomain, setCustomDomain] = useState<CustomDomainFetch>({ state: null, isLoading: true });
  const [websiteVersions, setWebsiteVersions] = useState<WebsiteVersionsFetch>({ versions: null, isLoading: true });
  const [readiness, setReadiness] = useState<ProductionReadinessFetch>({ report: null, isLoading: true });
  const [leads, setLeads] = useState<LeadsFetch>({ leads: null, isLoading: true, error: null });
  const [leadFilters, setLeadFilters] = useState<LeadFilters>({});
  const [health, setHealth] = useState<WebsiteHealthFetch>({ health: null, isLoading: true });
  const [metricsWindow, setMetricsWindow] = useState<MetricsWindow>("30d");
  const [metrics, setMetrics] = useState<BusinessMetricsFetch>({ metrics: null, isLoading: true });
  // Real logo/photo assets (LR-05) — fetched here, not only inside the
  // lazily-mounted CreativeSection, because the site preview below and
  // the exact SiteConfig WebsitePublish sends both need them to actually
  // show/publish a business's real brand assets, not only its text.
  const [businessAssets, setBusinessAssets] = useState<BusinessAssetsFetch>({ assets: null, isLoading: true });
  const [reloadToken, setReloadToken] = useState(0);
  // CreativeSection fetches its own data (creative-config/assets/reviews/
  // generations) independently of the four calls above — mounting it
  // only once a user actually opens it, rather than unconditionally
  // alongside this step, keeps those extra requests from firing (and
  // racing with these) for the common case of a user who never touches
  // brand/content tools during this visit.
  const [showCreative, setShowCreative] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setWorkflowState((prev) => ({ ...prev, isLoading: true, error: null }));
    setAutomation((prev) => ({ ...prev, isLoading: true }));
    setWebsite((prev) => ({ ...prev, isLoading: true }));
    setCustomDomain((prev) => ({ ...prev, isLoading: true }));
    setWebsiteVersions((prev) => ({ ...prev, isLoading: true }));
    setReadiness((prev) => ({ ...prev, isLoading: true }));
    setLeads((prev) => ({ ...prev, isLoading: true, error: null }));
    setBusinessAssets((prev) => ({ ...prev, isLoading: true }));

    getWorkflowPreview(business.id, tenantId)
      .then((workflow) => {
        if (!cancelled) setWorkflowState({ workflow, isLoading: false, error: null });
      })
      .catch((error: unknown) => {
        if (!cancelled) setWorkflowState({ workflow: null, isLoading: false, error: categorizeWorkflowPreviewError(error) });
      });

    // Independent of the preview call above: this is the *persisted*
    // activation state (backend's app.db.models.workflow.Workflow), the
    // real source of truth for Active/Inactive — reloaded fresh every
    // time this step opens, never assumed from local component state.
    getAutomationState(business.id, tenantId)
      .then((state) => {
        if (!cancelled) setAutomation({ state, isLoading: false });
      })
      .catch(() => {
        if (!cancelled) setAutomation({ state: null, isLoading: false });
      });

    // Same idea for the website's *persisted* deployment state (backend's
    // app.db.models.website.Website) — the real source of truth for
    // Published/Preview, reloaded fresh every time this step opens.
    getWebsiteState(business.id, tenantId)
      .then((state) => {
        if (!cancelled) setWebsite({ state, isLoading: false });
      })
      .catch(() => {
        if (!cancelled) setWebsite({ state: null, isLoading: false });
      });

    getLeads(business.id, tenantId, leadFilters)
      .then((fetched) => {
        if (!cancelled) setLeads({ leads: fetched, isLoading: false, error: null });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setLeads({ leads: null, isLoading: false, error: friendlyErrorMessage(error, "Unknown error") });
        }
      });

    // Same idea for the business's *persisted* custom-domain attachment
    // state (backend's app.db.models.custom_domain.CustomDomain) — fetched
    // last since it's the newest, least core of these five calls.
    getCustomDomain(business.id, tenantId)
      .then((state) => {
        if (!cancelled) setCustomDomain({ state, isLoading: false });
      })
      .catch(() => {
        if (!cancelled) setCustomDomain({ state: null, isLoading: false });
      });

    // Same idea for this business's *persisted* publish history
    // (backend's app.db.models.website_version.WebsiteVersion) — fetched
    // last, same reasoning as the custom-domain fetch above.
    getWebsiteVersions(business.id, tenantId)
      .then((versions) => {
        if (!cancelled) setWebsiteVersions({ versions, isLoading: false });
      })
      .catch(() => {
        if (!cancelled) setWebsiteVersions({ versions: null, isLoading: false });
      });

    // Same idea for the read-only production-readiness checklist
    // (backend's app.publishing.readiness) — fetched last, same
    // reasoning as the calls above.
    getProductionReadiness(business.id, tenantId)
      .then((report) => {
        if (!cancelled) setReadiness({ report, isLoading: false });
      })
      .catch(() => {
        if (!cancelled) setReadiness({ report: null, isLoading: false });
      });

    // Same idea for this business's real asset library (backend's
    // app.db.models.business_asset.BusinessAsset) — the real logo/photos
    // a generated site should use (LR-05), fetched last, same reasoning
    // as the calls above.
    listBusinessAssets(business.id, tenantId)
      .then((assets) => {
        if (!cancelled) setBusinessAssets({ assets, isLoading: false });
      })
      .catch(() => {
        if (!cancelled) setBusinessAssets({ assets: null, isLoading: false });
      });

    return () => {
      cancelled = true;
    };
  }, [business.id, tenantId, reloadToken, leadFilters]);

  useEffect(() => {
    let cancelled = false;
    setHealth((prev) => ({ ...prev, isLoading: true }));
    getWebsiteHealth(business.id, tenantId)
      .then((fetched) => {
        if (!cancelled) setHealth({ health: fetched, isLoading: false });
      })
      .catch(() => {
        if (!cancelled) setHealth({ health: null, isLoading: false });
      });
    return () => {
      cancelled = true;
    };
  }, [business.id, tenantId, reloadToken]);

  useEffect(() => {
    let cancelled = false;
    setMetrics((prev) => ({ ...prev, isLoading: true }));
    getBusinessMetrics(business.id, tenantId, metricsWindow)
      .then((fetched) => {
        if (!cancelled) setMetrics({ metrics: fetched, isLoading: false });
      })
      .catch(() => {
        if (!cancelled) setMetrics({ metrics: null, isLoading: false });
      });
    return () => {
      cancelled = true;
    };
  }, [business.id, tenantId, reloadToken, metricsWindow]);

  // Generated from the config exactly as the backend persisted it (see
  // CreatedBusiness.config's docstring) — the same generateSiteConfig()
  // a real website build would use, not a parallel preview-only path.
  // Publishing (below) sends this exact object, never a separately
  // recomputed one. Includes this business's real assets (LR-05) so a
  // real logo/photo is what gets previewed *and* published — never
  // silently dropped between "what Studio shows" and "what goes live".
  const siteConfig = useMemo(
    () => (business.config ? generateSiteConfig(business.config, businessAssets.assets ?? []) : null),
    [business.config, businessAssets.assets],
  );

  return (
    <div className="preview-step">
      <div className="banner banner--ok">
        <p>
          Business "{business.name}" created (slug: {business.slug}, status: {business.status}).
        </p>
      </div>

      <h2>Production readiness</h2>
      <ProductionReadinessPanel report={readiness.report} isLoading={readiness.isLoading} />

      <h2>Website health</h2>
      <WebsiteHealthPanel
        health={health.health}
        isLoading={health.isLoading}
        onCheckNow={() =>
          checkWebsiteHealthNow(business.id, tenantId).then((fetched) => {
            setHealth({ health: fetched, isLoading: false });
            return fetched;
          })
        }
      />

      <h2>Business metrics</h2>
      <BusinessMetricsPanel
        metrics={metrics.metrics}
        isLoading={metrics.isLoading}
        window={metricsWindow}
        onWindowChange={setMetricsWindow}
      />

      <h2>Website preview</h2>
      {siteConfig ? (
        <SiteConfigPreview siteConfig={siteConfig} />
      ) : (
        <p className="field-hint">This business has no configuration yet, so there's no website to preview.</p>
      )}
      <WebsitePublish
        siteConfig={siteConfig}
        websiteState={website.state}
        isLoadingWebsiteState={website.isLoading}
        customDomain={customDomain.state}
        onPublish={(config) =>
          publishWebsite(business.id, tenantId, config).then((state) => {
            setWebsite({ state, isLoading: false });
            return state;
          })
        }
      />

      <h2>Version history</h2>
      <WebsiteVersionsPanel
        versions={websiteVersions.versions}
        isLoading={websiteVersions.isLoading}
        onRollback={(versionId) =>
          rollbackToWebsiteVersion(business.id, versionId, tenantId).then((state) => {
            setWebsite({ state, isLoading: false });
            setReloadToken((n) => n + 1);
            return state;
          })
        }
      />

      <h2 id="custom-domain-section">Custom domain</h2>
      <CustomDomainPanel
        websiteState={website.state}
        customDomain={customDomain.state}
        isLoading={customDomain.isLoading}
        onAttach={(domain) =>
          attachCustomDomain(business.id, domain, tenantId).then((state) => {
            setCustomDomain({ state, isLoading: false });
            return state;
          })
        }
        onRefresh={() =>
          refreshCustomDomain(business.id, tenantId).then((state) => {
            setCustomDomain({ state, isLoading: false });
            return state;
          })
        }
        onDetach={() =>
          detachCustomDomain(business.id, tenantId).then((state) => {
            setCustomDomain({ state: state.status === "removed" ? null : state, isLoading: false });
            return state;
          })
        }
      />

      <h2>Automation preview</h2>
      <WorkflowPreview
        workflow={workflowState.workflow}
        isLoading={workflowState.isLoading}
        error={workflowState.error}
        automationState={automation.state}
        isLoadingAutomationState={automation.isLoading}
        onActivate={() =>
          activateAutomation(business.id, tenantId).then((state) => {
            setAutomation({ state, isLoading: false });
            return state;
          })
        }
        onDeactivate={() =>
          deactivateAutomation(business.id, tenantId).then((state) => {
            setAutomation({ state, isLoading: false });
            return state;
          })
        }
      />

      <h2>Creative</h2>
      {showCreative ? (
        <CreativeSection business={business} tenantId={tenantId} reloadToken={reloadToken} />
      ) : (
        <button type="button" onClick={() => setShowCreative(true)}>
          Show brand, content & generation tools
        </button>
      )}

      <h2>Leads</h2>
      <LeadsList
        leads={leads.leads}
        isLoading={leads.isLoading}
        error={leads.error}
        businessId={business.id}
        tenantId={tenantId}
        filters={leadFilters}
        onFiltersChange={setLeadFilters}
        onUpdateStatus={(leadId: string, status: LeadStatus) =>
          updateLeadStatus(business.id, leadId, status, tenantId).then((updated) => {
            setLeads((prev) => ({
              ...prev,
              leads: prev.leads ? prev.leads.map((lead) => (lead.id === updated.id ? updated : lead)) : prev.leads,
            }));
            return updated;
          })
        }
      />

      <div className="proposal-actions">
        <button type="button" onClick={onEdit}>
          Edit business
        </button>
        <button type="button" onClick={() => setReloadToken((n) => n + 1)}>
          Refresh
        </button>
        <button type="button" onClick={onCreateAnother}>
          Create another
        </button>
      </div>
    </div>
  );
}
