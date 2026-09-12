import type { CreativeConfig } from "@generate-web-ai/business-config-types";
import { generateSiteConfig } from "@generate-web-ai/website-generator";
import { useEffect, useState } from "react";
import { friendlyErrorMessage } from "../business-analysis/errors";
import {
  approveWebsiteDraft,
  createBusinessAsset,
  createBusinessReview,
  createCreativeGeneration,
  createWebsiteDraft,
  deleteBusinessAsset,
  deleteBusinessReview,
  updateBusinessReviewVisibility,
  getCreativeConfig,
  listBusinessAssets,
  listBusinessReviews,
  listCreativeGenerations,
  listCreativeProviders,
  listWebsiteDrafts,
  publishWebsiteDraft,
  updateCreativeConfig,
  uploadBusinessAsset,
  uploadBusinessAssetsBatch,
  type BusinessAsset,
  type BusinessReview,
  type CreatedBusiness,
  type CreativeGeneration,
  type CreativeProviderAvailability,
  type WebsiteDraft,
} from "../../lib/api";
import { AssetsPanel } from "./AssetsPanel";
import { CreativeConfigPanel } from "./CreativeConfigPanel";
import { GenerationsPanel } from "./GenerationsPanel";
import { GenerativeWorkflowPanel } from "./GenerativeWorkflowPanel";
import { ProvidersPanel } from "./ProvidersPanel";
import { ReviewsPanel } from "./ReviewsPanel";
import { WebsiteDraftsPanel } from "./WebsiteDraftsPanel";

interface CreativeSectionProps {
  business: CreatedBusiness;
  tenantId: string;
  /** Bumped by the parent's own "Refresh" action (see PreviewStep) so
   * this section's data reloads alongside everything else on the page,
   * without this component needing to know why. */
  reloadToken: number;
}

interface Fetched<T> {
  data: T | null;
  isLoading: boolean;
  error: string | null;
}

const LOADING = { isLoading: true, error: null } as const;

/** Brand & Content / Creative — Phase 12's Studio integration: provider
 * availability, strategy & level, the business's asset library, its real
 * reviews, generation history/trigger, and the generated-preview ->
 * approve -> publish lifecycle, all scoped to this one business. Owns its
 * own data fetching (independent of PreviewStep's leads/website/
 * automation state) since these concerns are cohesive but don't feed
 * each other — see each Panel's own docstring for what it does. */
export function CreativeSection({ business, tenantId, reloadToken }: CreativeSectionProps) {
  const businessId = business.id;

  const [providers, setProviders] = useState<Fetched<CreativeProviderAvailability[]>>({ data: null, ...LOADING });
  const [config, setConfig] = useState<Fetched<CreativeConfig>>({ data: null, ...LOADING });
  const [assets, setAssets] = useState<Fetched<BusinessAsset[]>>({ data: null, ...LOADING });
  const [reviews, setReviews] = useState<Fetched<BusinessReview[]>>({ data: null, ...LOADING });
  const [generations, setGenerations] = useState<Fetched<CreativeGeneration[]>>({ data: null, ...LOADING });
  const [drafts, setDrafts] = useState<Fetched<WebsiteDraft[]>>({ data: null, ...LOADING });
  const [autoDraftError, setAutoDraftError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setProviders((prev) => ({ ...prev, isLoading: true, error: null }));
    setConfig((prev) => ({ ...prev, isLoading: true, error: null }));
    setAssets((prev) => ({ ...prev, isLoading: true, error: null }));
    setReviews((prev) => ({ ...prev, isLoading: true, error: null }));
    setGenerations((prev) => ({ ...prev, isLoading: true, error: null }));
    setDrafts((prev) => ({ ...prev, isLoading: true, error: null }));

    listCreativeProviders(businessId, tenantId)
      .then((data) => !cancelled && setProviders({ data, isLoading: false, error: null }))
      .catch((error: unknown) => !cancelled && setProviders({ data: null, isLoading: false, error: friendlyErrorMessage(error, "Unknown error") }));

    getCreativeConfig(businessId, tenantId)
      .then((data) => !cancelled && setConfig({ data, isLoading: false, error: null }))
      .catch((error: unknown) => !cancelled && setConfig({ data: null, isLoading: false, error: friendlyErrorMessage(error, "Unknown error") }));

    listBusinessAssets(businessId, tenantId)
      .then((data) => !cancelled && setAssets({ data, isLoading: false, error: null }))
      .catch((error: unknown) => !cancelled && setAssets({ data: null, isLoading: false, error: friendlyErrorMessage(error, "Unknown error") }));

    listBusinessReviews(businessId, tenantId)
      .then((data) => !cancelled && setReviews({ data, isLoading: false, error: null }))
      .catch((error: unknown) => !cancelled && setReviews({ data: null, isLoading: false, error: friendlyErrorMessage(error, "Unknown error") }));

    listCreativeGenerations(businessId, tenantId)
      .then((data) => !cancelled && setGenerations({ data, isLoading: false, error: null }))
      .catch((error: unknown) => !cancelled && setGenerations({ data: null, isLoading: false, error: friendlyErrorMessage(error, "Unknown error") }));

    listWebsiteDrafts(businessId, tenantId)
      .then((data) => !cancelled && setDrafts({ data, isLoading: false, error: null }))
      .catch((error: unknown) => !cancelled && setDrafts({ data: null, isLoading: false, error: friendlyErrorMessage(error, "Unknown error") }));

    return () => {
      cancelled = true;
    };
  }, [businessId, tenantId, reloadToken]);

  return (
    <div className="creative-section">
      <h3>Creative providers</h3>
      <ProvidersPanel providers={providers.data} isLoading={providers.isLoading} error={providers.error} />

      <h3>Creative strategy</h3>
      <CreativeConfigPanel
        config={config.data}
        isLoading={config.isLoading}
        onSave={(next) => updateCreativeConfig(businessId, next, tenantId)}
      />

      <h3>Business photos & brand assets</h3>
      <AssetsPanel
        assets={assets.data}
        isLoading={assets.isLoading}
        error={assets.error}
        onUpload={(file, kind, category, altText) =>
          uploadBusinessAsset(businessId, file, { kind, category, altText: altText || null }, tenantId).then(
            (created) => {
              setAssets((prev) => ({ ...prev, data: [created, ...(prev.data ?? [])] }));
              return created;
            },
          )
        }
        onUploadBatch={(files, category) =>
          uploadBusinessAssetsBatch(businessId, files, { kind: "image", category }, tenantId).then((results) => {
            const created = results.filter((result) => result.success && result.asset).map((result) => result.asset!);
            if (created.length > 0) {
              setAssets((prev) => ({ ...prev, data: [...created, ...(prev.data ?? [])] }));
            }
            return results;
          })
        }
        onAdd={(payload) =>
          createBusinessAsset(businessId, payload, tenantId).then((created) => {
            setAssets((prev) => ({ ...prev, data: [created, ...(prev.data ?? [])] }));
            return created;
          })
        }
        onDelete={(assetId) =>
          deleteBusinessAsset(businessId, assetId, tenantId).then(() => {
            setAssets((prev) => ({ ...prev, data: (prev.data ?? []).filter((asset) => asset.id !== assetId) }));
          })
        }
      />

      <h3>Google reviews</h3>
      <ReviewsPanel
        reviews={reviews.data}
        isLoading={reviews.isLoading}
        error={reviews.error}
        onAdd={(payload) =>
          createBusinessReview(businessId, payload, tenantId).then((created) => {
            setReviews((prev) => ({ ...prev, data: [created, ...(prev.data ?? [])] }));
            return created;
          })
        }
        onDelete={(reviewId) =>
          deleteBusinessReview(businessId, reviewId, tenantId).then(() => {
            setReviews((prev) => ({ ...prev, data: (prev.data ?? []).filter((review) => review.id !== reviewId) }));
          })
        }
        onToggleVisibility={(reviewId, isVisible) =>
          updateBusinessReviewVisibility(businessId, reviewId, isVisible, tenantId).then((updated) => {
            setReviews((prev) => ({
              ...prev,
              data: (prev.data ?? []).map((review) => (review.id === updated.id ? updated : review)),
            }));
            return updated;
          })
        }
      />

      <h3>Generate website</h3>
      {autoDraftError && (
        <p className="banner banner--error">Generation succeeded, but building a preview failed: {autoDraftError}</p>
      )}
      <GenerationsPanel
        generations={generations.data}
        isLoading={generations.isLoading}
        error={generations.error}
        providers={providers.data}
        onGenerate={(generationType) =>
          createCreativeGeneration(businessId, generationType, tenantId).then((generation) => {
            setGenerations((prev) => ({ ...prev, data: [generation, ...(prev.data ?? [])] }));

            // The InternalCreativeProvider's own "website" result carries
            // no content of its own (see app.creative.internal's
            // docstring on the backend) — the actual SiteConfig is
            // computed here, exactly the same generateSiteConfig() call
            // PreviewStep's own live preview already uses (including
            // this business's real assets, LR-05), then persisted as a
            // safe draft (Phase 7/8). A future successful Higgsfield
            // generation would carry its own output instead; this
            // auto-draft step only applies to Internal's website results.
            //
            // Both branches below are reachable failure states a
            // previous version of this code silently swallowed (LR-03):
            // no `business.config` yet (generation succeeded before the
            // business proposal was ever completed) and a synchronous
            // generateSiteConfig() throw (a malformed/incomplete
            // config) — both used to leave the generation showing
            // "Completed" with no explanation for why no preview ever
            // appeared. Both now surface through the same
            // `autoDraftError` banner the network-failure case already used.
            if (generation.status === "completed" && generation.provider === "internal" && generation.generation_type === "website") {
              if (!business.config) {
                setAutoDraftError(
                  "This business has no completed proposal yet — finish the business proposal before generating a website.",
                );
              } else {
                setAutoDraftError(null);
                try {
                  const siteConfig = generateSiteConfig(business.config, assets.data ?? []);
                  createWebsiteDraft(businessId, siteConfig, generation.id, tenantId)
                    .then((draft) => {
                      setDrafts((prev) => ({ ...prev, data: [draft, ...(prev.data ?? [])] }));
                    })
                    .catch((caught: unknown) => {
                      setAutoDraftError(friendlyErrorMessage(caught, "Could not build a preview from this generation."));
                    });
                } catch (caught) {
                  setAutoDraftError(friendlyErrorMessage(caught, "Could not build a preview from this generation."));
                }
              }
            }

            return generation;
          })
        }
      />

      <h3>Generated preview</h3>
      <WebsiteDraftsPanel
        drafts={drafts.data}
        isLoading={drafts.isLoading}
        error={drafts.error}
        onApprove={(draftId) =>
          approveWebsiteDraft(businessId, draftId, tenantId).then((updated) => {
            setDrafts((prev) => ({
              ...prev,
              data: (prev.data ?? []).map((draft) => (draft.id === updated.id ? updated : draft)),
            }));
            return updated;
          })
        }
        onPublish={(draftId) =>
          publishWebsiteDraft(businessId, draftId, tenantId).then((state) => {
            setDrafts((prev) => ({
              ...prev,
              data: (prev.data ?? []).map((draft) =>
                draft.id === draftId ? { ...draft, status: "published", published_at: new Date().toISOString() } : draft,
              ),
            }));
            return state;
          })
        }
      />

      <h3>Generate website with AI (experimental)</h3>
      <GenerativeWorkflowPanel
        businessId={businessId}
        tenantId={tenantId}
        generativeDrafts={(drafts.data ?? []).filter((draft) => draft.engine === "generative")}
        onDraftCreated={(draft) => setDrafts((prev) => ({ ...prev, data: [draft, ...(prev.data ?? [])] }))}
        onApprove={(draftId) =>
          approveWebsiteDraft(businessId, draftId, tenantId).then((updated) => {
            setDrafts((prev) => ({
              ...prev,
              data: (prev.data ?? []).map((draft) => (draft.id === updated.id ? updated : draft)),
            }));
            return updated;
          })
        }
        onPublish={(draftId) =>
          publishWebsiteDraft(businessId, draftId, tenantId).then((state) => {
            setDrafts((prev) => ({
              ...prev,
              data: (prev.data ?? []).map((draft) =>
                draft.id === draftId ? { ...draft, status: "published", published_at: new Date().toISOString() } : draft,
              ),
            }));
            return state;
          })
        }
      />
    </div>
  );
}
