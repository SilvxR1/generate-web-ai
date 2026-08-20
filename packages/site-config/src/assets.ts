/**
 * Structural shape of an Astro-imported local image (an ESM `import img
 * from "./photo.jpg"`). Declared independently here rather than imported
 * from `astro`'s own `ImageMetadata` type, for the same reason the rest of
 * this file avoids an Astro dependency: a real `ImageMetadata` value
 * satisfies this shape for free, so nothing is lost, but this package's
 * public types stay describable without Astro's tooling.
 */
export interface LocalImageRef {
  src: string;
  width: number;
  height: number;
  format: string;
}

/**
 * A single reusable image reference. `alt` is required so anything built
 * from this type — a brand logo, a block image — stays accessible by
 * construction.
 *
 * `src` accepts either a plain URL/path (a remote image, or one already
 * placed in `public/`) or a `LocalImageRef` (the object produced by
 * importing a local image file). Only the latter carries the metadata
 * `@generate-web-ai/ui`'s `Media` component needs to generate a real
 * responsive `srcset`/format set via `astro:assets` — a plain string still
 * renders correctly, just without that optimization.
 */
export interface AssetConfig {
  src: string | LocalImageRef;
  alt: string;
  width?: number;
  height?: number;
}
