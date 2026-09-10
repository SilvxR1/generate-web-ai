import { useState } from "react";
import { friendlyErrorMessage } from "../business-analysis/errors";
import type { AssetCategory, AssetKind, AssetOrigin, BusinessAsset, CreateAssetPayload } from "../../lib/api";

interface AssetsPanelProps {
  assets: BusinessAsset[] | null;
  isLoading: boolean;
  error: string | null;
  /** POST .../assets/upload (app.routers.creative) — a real file this
   * component sends as multipart/form-data. The primary way to add a
   * logo or business photo (Phase 3/15). */
  onUpload: (file: File, kind: AssetKind, category: AssetCategory, altText: string) => Promise<BusinessAsset>;
  /** POST .../assets — registers a URL already hosted elsewhere (an
   * imported or provider-generated asset), never a file this component
   * sends itself. Kept as a secondary, "advanced" option. */
  onAdd: (payload: CreateAssetPayload) => Promise<BusinessAsset>;
  onDelete: (assetId: string) => Promise<void>;
}

const KIND_OPTIONS: AssetKind[] = ["logo", "image", "video", "document"];
const CATEGORY_OPTIONS: AssetCategory[] = [
  "logo",
  "project",
  "team",
  "facility",
  "product",
  "before",
  "after",
  "hero_candidate",
  "gallery",
  "other",
  "low_quality",
];
const ORIGIN_OPTIONS: AssetOrigin[] = ["uploaded", "imported", "generated"];

const EMPTY_URL_FORM = {
  kind: "image" as AssetKind,
  category: "other" as AssetCategory,
  origin: "imported" as AssetOrigin,
  storage_url: "",
  alt_text: "",
};

/** Business asset library (Section 2/3/14): real business photos, logo,
 * and generated media, each with a category and provenance (`origin`).
 * Two ways to add one: upload a real file (primary — Phase 15), or
 * register a URL already hosted elsewhere (secondary — an imported or
 * provider-generated asset this component never uploaded itself). */
export function AssetsPanel({ assets, isLoading, error, onUpload, onAdd, onDelete }: AssetsPanelProps) {
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadKind, setUploadKind] = useState<AssetKind>("image");
  const [uploadCategory, setUploadCategory] = useState<AssetCategory>("other");
  const [uploadAltText, setUploadAltText] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const [showUrlForm, setShowUrlForm] = useState(false);
  const [urlForm, setUrlForm] = useState(EMPTY_URL_FORM);
  const [isSubmittingUrl, setIsSubmittingUrl] = useState(false);
  const [urlFormError, setUrlFormError] = useState<string | null>(null);

  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);

  async function handleUpload() {
    if (!uploadFile) {
      setUploadError("Choose a file first.");
      return;
    }
    setIsUploading(true);
    setUploadError(null);
    try {
      await onUpload(uploadFile, uploadKind, uploadCategory, uploadAltText.trim());
      setUploadFile(null);
      setUploadAltText("");
    } catch (caught) {
      setUploadError(friendlyErrorMessage(caught, "Could not upload this file."));
    } finally {
      setIsUploading(false);
    }
  }

  async function handleAddUrl() {
    if (!urlForm.storage_url.trim()) {
      setUrlFormError("A storage URL is required.");
      return;
    }
    setIsSubmittingUrl(true);
    setUrlFormError(null);
    try {
      await onAdd({
        kind: urlForm.kind,
        category: urlForm.category,
        origin: urlForm.origin,
        storage_url: urlForm.storage_url.trim(),
        alt_text: urlForm.alt_text.trim() || null,
      });
      setUrlForm(EMPTY_URL_FORM);
    } catch (caught) {
      setUrlFormError(friendlyErrorMessage(caught, "Could not add this asset."));
    } finally {
      setIsSubmittingUrl(false);
    }
  }

  async function handleDelete(assetId: string) {
    setPendingDeleteId(assetId);
    try {
      await onDelete(assetId);
    } finally {
      setPendingDeleteId(null);
    }
  }

  return (
    <div className="assets-panel">
      {error && <p className="banner banner--error">Could not load assets: {error}</p>}
      {isLoading ? (
        <p className="field-hint">Loading assets…</p>
      ) : !assets || assets.length === 0 ? (
        <p className="field-hint">No brand/content assets yet.</p>
      ) : (
        <ul className="assets-panel__list">
          {assets.map((asset) => (
            <li key={asset.id} className="assets-panel__item">
              <img src={asset.storage_url} alt={asset.alt_text ?? ""} className="assets-panel__thumb" />
              <div>
                <div>
                  <strong>{asset.category}</strong> · {asset.kind} · {asset.origin}
                </div>
                <div className="field-hint">{asset.original_filename ?? asset.storage_url}</div>
              </div>
              <button type="button" onClick={() => handleDelete(asset.id)} disabled={pendingDeleteId === asset.id}>
                {pendingDeleteId === asset.id ? "Removing…" : "Remove"}
              </button>
            </li>
          ))}
        </ul>
      )}

      {uploadError && <p className="banner banner--error">{uploadError}</p>}
      <div className="assets-panel__form">
        <select value={uploadKind} onChange={(event) => setUploadKind(event.target.value as AssetKind)}>
          {KIND_OPTIONS.map((kind) => (
            <option key={kind} value={kind}>
              {kind}
            </option>
          ))}
        </select>
        <select value={uploadCategory} onChange={(event) => setUploadCategory(event.target.value as AssetCategory)}>
          {CATEGORY_OPTIONS.map((category) => (
            <option key={category} value={category}>
              {category}
            </option>
          ))}
        </select>
        <input
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif,image/svg+xml,video/mp4,video/webm,application/pdf"
          onChange={(event) => setUploadFile(event.target.files?.[0] ?? null)}
        />
        <input
          type="text"
          placeholder="Alt text"
          value={uploadAltText}
          onChange={(event) => setUploadAltText(event.target.value)}
        />
        <button type="button" onClick={handleUpload} disabled={isUploading || !uploadFile}>
          {isUploading ? "Uploading…" : "Upload"}
        </button>
      </div>

      <button type="button" onClick={() => setShowUrlForm((v) => !v)} className="assets-panel__toggle-url-form">
        {showUrlForm ? "Hide" : "Register an asset already hosted elsewhere"}
      </button>
      {showUrlForm && (
        <div className="assets-panel__form">
          {urlFormError && <p className="banner banner--error">{urlFormError}</p>}
          <select value={urlForm.kind} onChange={(event) => setUrlForm({ ...urlForm, kind: event.target.value as AssetKind })}>
            {KIND_OPTIONS.map((kind) => (
              <option key={kind} value={kind}>
                {kind}
              </option>
            ))}
          </select>
          <select
            value={urlForm.category}
            onChange={(event) => setUrlForm({ ...urlForm, category: event.target.value as AssetCategory })}
          >
            {CATEGORY_OPTIONS.map((category) => (
              <option key={category} value={category}>
                {category}
              </option>
            ))}
          </select>
          <select
            value={urlForm.origin}
            onChange={(event) => setUrlForm({ ...urlForm, origin: event.target.value as AssetOrigin })}
          >
            {ORIGIN_OPTIONS.map((origin) => (
              <option key={origin} value={origin}>
                {origin}
              </option>
            ))}
          </select>
          <input
            type="url"
            placeholder="https://…/photo.jpg"
            value={urlForm.storage_url}
            onChange={(event) => setUrlForm({ ...urlForm, storage_url: event.target.value })}
          />
          <input
            type="text"
            placeholder="Alt text"
            value={urlForm.alt_text}
            onChange={(event) => setUrlForm({ ...urlForm, alt_text: event.target.value })}
          />
          <button type="button" onClick={handleAddUrl} disabled={isSubmittingUrl}>
            {isSubmittingUrl ? "Adding…" : "Add asset"}
          </button>
        </div>
      )}
    </div>
  );
}
