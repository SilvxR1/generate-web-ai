// Shared content types used across multiple blocks. Kept intentionally
// small so AI-generated content stays predictable: a label/href pair for
// actions, and a src/alt pair for images.

/** A single call-to-action link. `variant` maps directly onto the `ui` Button variant. */
export interface BlockAction {
  label: string;
  href: string;
  variant?: "solid" | "outline" | "ghost";
}

/** An image reference. `alt` is required so blocks never render inaccessible images. */
export interface BlockImage {
  src: string;
  alt: string;
  width?: number;
  height?: number;
}
