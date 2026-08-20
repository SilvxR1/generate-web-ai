// Shared content types used across multiple blocks. Kept intentionally
// small so AI-generated content stays predictable: a label/href pair for
// actions, and a src/alt pair for images.

/** A single call-to-action link. `variant` maps directly onto the `ui` Button variant. */
export interface BlockAction {
  label: string;
  href: string;
  variant?: "solid" | "outline" | "ghost";
}

/**
 * Structural shape of an Astro-imported local image. Duplicated from
 * `@generate-web-ai/site-config`'s `LocalImageRef` rather than imported —
 * see that file's comment; the same reasoning applies here (this file
 * stays plain TypeScript, no Astro types, even though the package as a
 * whole does depend on Astro to compile its `.astro` components).
 */
export interface LocalImageRef {
  src: string;
  width: number;
  height: number;
  format: string;
}

/**
 * An image reference. `alt` is required so blocks never render inaccessible
 * images. `src` accepts a plain URL/path or a `LocalImageRef` — see
 * `@generate-web-ai/ui`'s `Media` component for what the latter enables.
 */
export interface BlockImage {
  src: string | LocalImageRef;
  alt: string;
  width?: number;
  height?: number;
}
