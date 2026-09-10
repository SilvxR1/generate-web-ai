import { useState } from "react";
import { friendlyErrorMessage } from "../business-analysis/errors";
import type { BusinessReview, CreateReviewPayload, ReviewSource } from "../../lib/api";

interface ReviewsPanelProps {
  reviews: BusinessReview[] | null;
  isLoading: boolean;
  error: string | null;
  onAdd: (payload: CreateReviewPayload) => Promise<BusinessReview>;
  onDelete: (reviewId: string) => Promise<void>;
  /** PATCH .../reviews/{id}/visibility (P1.6) — show/hide on the
   * generated website without deleting the review or its provenance. */
  onToggleVisibility: (reviewId: string, isVisible: boolean) => Promise<BusinessReview>;
}

const EMPTY_FORM = { source: "google" as ReviewSource, author_name: "", rating: "", body: "", review_url: "" };

/** Real, imported/provided customer reviews (Section 4) — never
 * fabricated by this app: there's no "generate a testimonial" action
 * anywhere here, only registering a review the caller asserts is real
 * (e.g. pasted from a real Google listing, with its public URL as
 * provenance). No live Google Reviews API integration exists yet — see
 * app.routers.creative's create_business_review docstring on the
 * backend. */
export function ReviewsPanel({ reviews, isLoading, error, onAdd, onDelete, onToggleVisibility }: ReviewsPanelProps) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [pendingVisibilityId, setPendingVisibilityId] = useState<string | null>(null);

  async function handleAdd() {
    if (!form.body.trim()) {
      setFormError("Review text is required.");
      return;
    }
    setIsSubmitting(true);
    setFormError(null);
    try {
      await onAdd({
        source: form.source,
        author_name: form.author_name.trim() || null,
        rating: form.rating ? Number(form.rating) : null,
        body: form.body.trim(),
        review_url: form.review_url.trim() || null,
      });
      setForm(EMPTY_FORM);
    } catch (caught) {
      setFormError(friendlyErrorMessage(caught, "Could not add this review."));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleDelete(reviewId: string) {
    setPendingDeleteId(reviewId);
    try {
      await onDelete(reviewId);
    } finally {
      setPendingDeleteId(null);
    }
  }

  async function handleToggleVisibility(review: BusinessReview) {
    setPendingVisibilityId(review.id);
    try {
      await onToggleVisibility(review.id, !review.is_visible);
    } finally {
      setPendingVisibilityId(null);
    }
  }

  return (
    <div className="reviews-panel">
      {error && <p className="banner banner--error">Could not load reviews: {error}</p>}
      {isLoading ? (
        <p className="field-hint">Loading reviews…</p>
      ) : !reviews || reviews.length === 0 ? (
        <p className="field-hint">No reviews imported yet.</p>
      ) : (
        <ul className="reviews-panel__list">
          {reviews.map((review) => (
            <li key={review.id} className="reviews-panel__item">
              <div>
                <strong>{review.author_name ?? "Anonymous"}</strong>
                {review.rating != null && <span> · {review.rating}/5</span>}
                <span className="field-hint"> · {review.source}</span>
                <span className="field-hint"> · {review.is_visible ? "Visible on website" : "Hidden"}</span>
              </div>
              <p>{review.body}</p>
              <button
                type="button"
                onClick={() => handleToggleVisibility(review)}
                disabled={pendingVisibilityId === review.id}
              >
                {pendingVisibilityId === review.id ? "Saving…" : review.is_visible ? "Hide" : "Show"}
              </button>
              <button
                type="button"
                onClick={() => handleDelete(review.id)}
                disabled={pendingDeleteId === review.id}
              >
                {pendingDeleteId === review.id ? "Removing…" : "Remove"}
              </button>
            </li>
          ))}
        </ul>
      )}

      {formError && <p className="banner banner--error">{formError}</p>}
      <div className="reviews-panel__form">
        <select
          value={form.source}
          onChange={(event) => setForm({ ...form, source: event.target.value as ReviewSource })}
        >
          <option value="google">Google (pasted)</option>
          <option value="manual">Manual</option>
          <option value="other">Other</option>
        </select>
        <input
          type="text"
          placeholder="Author name"
          value={form.author_name}
          onChange={(event) => setForm({ ...form, author_name: event.target.value })}
        />
        <input
          type="number"
          min={1}
          max={5}
          placeholder="Rating"
          value={form.rating}
          onChange={(event) => setForm({ ...form, rating: event.target.value })}
        />
        <textarea
          placeholder="What the customer actually wrote — pasted verbatim."
          value={form.body}
          onChange={(event) => setForm({ ...form, body: event.target.value })}
        />
        <input
          type="url"
          placeholder="Public review URL (optional, for provenance)"
          value={form.review_url}
          onChange={(event) => setForm({ ...form, review_url: event.target.value })}
        />
        <button type="button" onClick={handleAdd} disabled={isSubmitting}>
          {isSubmitting ? "Adding…" : "Add review"}
        </button>
      </div>
    </div>
  );
}
