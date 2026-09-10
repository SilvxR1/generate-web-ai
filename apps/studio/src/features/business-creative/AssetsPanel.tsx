import { useRef, useState } from "react";
import { friendlyErrorMessage } from "../business-analysis/errors";
import type {
  AssetCategory,
  AssetKind,
  AssetOrigin,
  BusinessAsset,
  BusinessAssetUploadResult,
  CreateAssetPayload,
} from "../../lib/api";

interface AssetsPanelProps {
  assets: BusinessAsset[] | null;
  isLoading: boolean;
  error: string | null;
  /** POST .../assets/upload (app.routers.creative) — a single real file,
   * used for the dedicated "Brand logo" uploader below (always
   * kind="logo", category="logo"). */
  onUpload: (file: File, kind: AssetKind, category: AssetCategory, altText: string) => Promise<BusinessAsset>;
  /** POST .../assets/upload-batch (LR-01) — many real photos in one
   * interaction, all sharing the same `category`. The primary way to
   * bring in 10-30 business photographs without repeating a form. */
  onUploadBatch: (files: File[], category: AssetCategory) => Promise<BusinessAssetUploadResult[]>;
  /** POST .../assets — registers a URL already hosted elsewhere (an
   * imported or provider-generated asset), never a file this component
   * sends itself. Kept as a secondary, "advanced" option. */
  onAdd: (payload: CreateAssetPayload) => Promise<BusinessAsset>;
  onDelete: (assetId: string) => Promise<void>;
}

// Human-readable labels for AssetCategory — the raw enum values
// (hero_candidate, before, after, ...) stay the values sent to the API,
// but an operator never needs to know that vocabulary exists (LR-01:
// "do not expose raw internal enum semantics unnecessarily").
const PHOTO_CATEGORY_LABELS: Partial<Record<AssetCategory, string>> = {
  gallery: "Gallery / portfolio",
  product: "Product photo",
  project: "Project / work sample",
  hero_candidate: "Hero photo (featured on the homepage)",
  before: "Before (renovation/comparison)",
  after: "After (renovation/comparison)",
  team: "Team photo",
  facility: "Facility / location",
  other: "Other",
};
const PHOTO_CATEGORY_OPTIONS: AssetCategory[] = [
  "gallery",
  "hero_candidate",
  "product",
  "project",
  "before",
  "after",
  "team",
  "facility",
  "other",
];

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

function isLogo(asset: BusinessAsset): boolean {
  return asset.kind === "logo" || asset.category === "logo";
}

/** Business asset library (Section 2/3/14): a business's brand logo and
 * its real product/business photos, each reusable across future
 * generations. Redesigned for real onboarding (LR-01): a dedicated,
 * single-image "Brand logo" uploader, a multi-file "Business & product
 * photos" gallery uploader, and a uniform preview grid that never lets
 * one huge portrait photo dominate the page. Registering a URL already
 * hosted elsewhere is kept, but demoted to an "Advanced" disclosure —
 * not competitive with normal upload during onboarding. */
export function AssetsPanel({ assets, isLoading, error, onUpload, onUploadBatch, onAdd, onDelete }: AssetsPanelProps) {
  const logoInputRef = useRef<HTMLInputElement>(null);
  const [logoFile, setLogoFile] = useState<File | null>(null);
  const [isUploadingLogo, setIsUploadingLogo] = useState(false);
  const [logoError, setLogoError] = useState<string | null>(null);

  const photoInputRef = useRef<HTMLInputElement>(null);
  const [photoFiles, setPhotoFiles] = useState<File[]>([]);
  const [photoCategory, setPhotoCategory] = useState<AssetCategory>("gallery");
  const [isUploadingPhotos, setIsUploadingPhotos] = useState(false);
  const [photoUploadResults, setPhotoUploadResults] = useState<BusinessAssetUploadResult[] | null>(null);
  const [isDraggingPhotos, setIsDraggingPhotos] = useState(false);

  const [urlForm, setUrlForm] = useState(EMPTY_URL_FORM);
  const [isSubmittingUrl, setIsSubmittingUrl] = useState(false);
  const [urlFormError, setUrlFormError] = useState<string | null>(null);

  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [lightboxAsset, setLightboxAsset] = useState<BusinessAsset | null>(null);

  const logo = (assets ?? []).find(isLogo) ?? null;
  const photos = (assets ?? []).filter((asset) => !isLogo(asset));

  async function handleUploadLogo() {
    if (!logoFile) return;
    setIsUploadingLogo(true);
    setLogoError(null);
    try {
      await onUpload(logoFile, "logo", "logo", "");
      setLogoFile(null);
      if (logoInputRef.current) logoInputRef.current.value = "";
    } catch (caught) {
      setLogoError(friendlyErrorMessage(caught, "Could not upload this logo."));
    } finally {
      setIsUploadingLogo(false);
    }
  }

  async function handleUploadPhotos() {
    if (photoFiles.length === 0) return;
    setIsUploadingPhotos(true);
    setPhotoUploadResults(null);
    try {
      const results = await onUploadBatch(photoFiles, photoCategory);
      setPhotoUploadResults(results);
      if (results.every((result) => result.success)) {
        setPhotoFiles([]);
        if (photoInputRef.current) photoInputRef.current.value = "";
      } else {
        // Keep only the files that failed selected, so the operator can
        // fix and retry without re-picking everything (LR-01: "show
        // per-file failures without losing successful uploads").
        const failedNames = new Set(results.filter((r) => !r.success).map((r) => r.filename));
        setPhotoFiles((prev) => prev.filter((file) => failedNames.has(file.name)));
      }
    } catch (caught) {
      setPhotoUploadResults([
        { filename: null, success: false, asset: null, error: friendlyErrorMessage(caught, "Upload failed.") },
      ]);
    } finally {
      setIsUploadingPhotos(false);
    }
  }

  function addPhotoFiles(fileList: FileList | File[]) {
    const incoming = Array.from(fileList).filter((file) => file.type.startsWith("image/"));
    setPhotoFiles((prev) => {
      const existingKeys = new Set(prev.map((file) => `${file.name}:${file.size}`));
      const deduped = incoming.filter((file) => !existingKeys.has(`${file.name}:${file.size}`));
      return [...prev, ...deduped];
    });
  }

  function removePendingPhoto(index: number) {
    setPhotoFiles((prev) => prev.filter((_, i) => i !== index));
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
      {isLoading && <p className="field-hint">Loading assets…</p>}

      {/* --- Brand logo ------------------------------------------------ */}
      <h4 className="assets-panel__subheading">Brand logo</h4>
      <p className="field-hint">Used in the website's header. Upload one image — a new upload replaces it.</p>
      {logo && (
        <ul className="assets-panel__grid assets-panel__grid--logo">
          <AssetCard asset={logo} onDelete={handleDelete} onEnlarge={setLightboxAsset} pendingDelete={pendingDeleteId === logo.id} />
        </ul>
      )}
      {logoError && <p className="banner banner--error">{logoError}</p>}
      <div className="assets-panel__upload-row">
        <input
          ref={logoInputRef}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/svg+xml"
          onChange={(event) => setLogoFile(event.target.files?.[0] ?? null)}
        />
        <button type="button" onClick={handleUploadLogo} disabled={isUploadingLogo || !logoFile}>
          {isUploadingLogo ? "Uploading…" : logo ? "Replace logo" : "Upload logo"}
        </button>
      </div>

      {/* --- Business & product photos ---------------------------------- */}
      <h4 className="assets-panel__subheading">Business &amp; product photos</h4>
      <p className="field-hint">
        Real photos of your products, work, team, or location. Select as many as you like and upload them together.
      </p>

      {photos.length > 0 && (
        <ul className="assets-panel__grid">
          {photos.map((asset) => (
            <AssetCard
              key={asset.id}
              asset={asset}
              onDelete={handleDelete}
              onEnlarge={setLightboxAsset}
              pendingDelete={pendingDeleteId === asset.id}
            />
          ))}
        </ul>
      )}
      {photos.length === 0 && !isLoading && <p className="field-hint">No business photos yet.</p>}

      <div
        className="assets-panel__dropzone"
        data-dragging={isDraggingPhotos ? "true" : "false"}
        onDragOver={(event) => {
          event.preventDefault();
          setIsDraggingPhotos(true);
        }}
        onDragLeave={() => setIsDraggingPhotos(false)}
        onDrop={(event) => {
          event.preventDefault();
          setIsDraggingPhotos(false);
          addPhotoFiles(event.dataTransfer.files);
        }}
      >
        <p>Drag photos here, or choose files below.</p>
        <input
          ref={photoInputRef}
          type="file"
          multiple
          accept="image/png,image/jpeg,image/webp,image/gif"
          onChange={(event) => {
            if (event.target.files) addPhotoFiles(event.target.files);
          }}
        />
      </div>

      {photoFiles.length > 0 && (
        <>
          <p className="field-hint">{photoFiles.length} photo(s) selected, not yet uploaded:</p>
          <ul className="assets-panel__pending-list">
            {photoFiles.map((file, index) => (
              <li key={`${file.name}-${index}`} className="assets-panel__pending-item">
                <img src={URL.createObjectURL(file)} alt="" className="assets-panel__pending-thumb" />
                <span className="assets-panel__pending-name">{file.name}</span>
                <button type="button" onClick={() => removePendingPhoto(index)} disabled={isUploadingPhotos}>
                  Remove
                </button>
              </li>
            ))}
          </ul>
          <div className="assets-panel__upload-row">
            <label className="assets-panel__category-label">
              What do these photos show?
              <select value={photoCategory} onChange={(event) => setPhotoCategory(event.target.value as AssetCategory)}>
                {PHOTO_CATEGORY_OPTIONS.map((category) => (
                  <option key={category} value={category}>
                    {PHOTO_CATEGORY_LABELS[category] ?? category}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" onClick={handleUploadPhotos} disabled={isUploadingPhotos}>
              {isUploadingPhotos ? "Uploading…" : `Upload ${photoFiles.length} photo(s)`}
            </button>
          </div>
        </>
      )}

      {photoUploadResults && photoUploadResults.some((result) => !result.success) && (
        <div className="banner banner--error">
          <p>Some photos could not be uploaded:</p>
          <ul>
            {photoUploadResults
              .filter((result) => !result.success)
              .map((result, index) => (
                <li key={`${result.filename ?? "file"}-${index}`}>
                  {result.filename ?? "A file"}: {result.error ?? "Unknown error"}
                </li>
              ))}
          </ul>
        </div>
      )}
      {photoUploadResults && photoUploadResults.every((result) => result.success) && photoUploadResults.length > 0 && (
        <p className="banner banner--ok">Uploaded {photoUploadResults.length} photo(s).</p>
      )}

      {/* --- Advanced: hosted elsewhere ---------------------------------- */}
      <details className="assets-panel__advanced">
        <summary>Advanced: register an asset already hosted elsewhere</summary>
        <p className="field-hint">
          For an asset that already lives at a real URL (e.g. imported, or produced by a creative provider) — most
          businesses never need this.
        </p>
        <div className="assets-panel__form">
          <label>
            Media type
            <select value={urlForm.kind} onChange={(event) => setUrlForm({ ...urlForm, kind: event.target.value as AssetKind })}>
              {KIND_OPTIONS.map((kind) => (
                <option key={kind} value={kind}>
                  {kind}
                </option>
              ))}
            </select>
          </label>
          <label>
            Category
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
          </label>
          <label>
            Source
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
          </label>
          <label>
            URL
            <input
              type="url"
              placeholder="https://…/photo.jpg"
              value={urlForm.storage_url}
              onChange={(event) => setUrlForm({ ...urlForm, storage_url: event.target.value })}
            />
          </label>
          <label>
            Image description (optional)
            <input
              type="text"
              placeholder="Briefly describe the image, for accessibility"
              value={urlForm.alt_text}
              onChange={(event) => setUrlForm({ ...urlForm, alt_text: event.target.value })}
            />
          </label>
          {urlFormError && <p className="banner banner--error">{urlFormError}</p>}
          <button type="button" onClick={handleAddUrl} disabled={isSubmittingUrl}>
            {isSubmittingUrl ? "Adding…" : "Add asset"}
          </button>
        </div>
      </details>

      {lightboxAsset && (
        <div className="assets-panel__lightbox" onClick={() => setLightboxAsset(null)}>
          <img src={lightboxAsset.storage_url} alt={lightboxAsset.alt_text ?? ""} />
        </div>
      )}
    </div>
  );
}

function AssetCard({
  asset,
  onDelete,
  onEnlarge,
  pendingDelete,
}: {
  asset: BusinessAsset;
  onDelete: (assetId: string) => void;
  onEnlarge: (asset: BusinessAsset) => void;
  pendingDelete: boolean;
}) {
  const logo = isLogo(asset);
  return (
    <li className={`assets-panel__card ${logo ? "assets-panel__card--logo" : "assets-panel__card--photo"}`}>
      <button type="button" className="assets-panel__card-media" onClick={() => onEnlarge(asset)}>
        <img src={asset.storage_url} alt={asset.alt_text ?? ""} />
      </button>
      <div className="assets-panel__card-body">
        <span className="assets-panel__card-label">{PHOTO_CATEGORY_LABELS[asset.category] ?? asset.category}</span>
        <button type="button" onClick={() => onDelete(asset.id)} disabled={pendingDelete}>
          {pendingDelete ? "Removing…" : "Remove"}
        </button>
      </div>
    </li>
  );
}
