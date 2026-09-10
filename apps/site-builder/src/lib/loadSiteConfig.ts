/**
 * Shared by every page file in this app (index.astro, [...slug].astro):
 * reads the SiteConfig JSON at SITE_CONFIG_PATH, or falls back to
 * @generate-web-ai/site-config's own exampleSiteConfig when it's unset
 * — the same "validation fixture, not a client site" role
 * apps/site-template's example.astro plays, so `astro build` still
 * succeeds standalone (e.g. a bare `turbo run build`) without the real
 * publishing pipeline setting SITE_CONFIG_PATH.
 */
import fs from "node:fs";
import type { SiteConfig } from "@generate-web-ai/site-config";
import { exampleSiteConfig } from "@generate-web-ai/site-config";

export function loadSiteConfig(): SiteConfig {
  const configPath = process.env.SITE_CONFIG_PATH;
  return configPath ? JSON.parse(fs.readFileSync(configPath, "utf-8")) : exampleSiteConfig;
}
