import type { AssetConfig } from "./assets.ts";

export interface BrandConfig {
  name: string;
  logo?: AssetConfig;
  tagline?: string;
}
