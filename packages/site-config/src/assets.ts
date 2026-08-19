/**
 * A single reusable image reference. `alt` is required so anything built
 * from this type — a brand logo, a block image — stays accessible by
 * construction.
 */
export interface AssetConfig {
  src: string;
  alt: string;
  width?: number;
  height?: number;
}
