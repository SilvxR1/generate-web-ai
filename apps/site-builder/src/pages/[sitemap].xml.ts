/**
 * C2.1: sitemap.xml, emitted only when the SiteConfig has a verified
 * canonical origin (siteUrl) — a sitemap needs absolute URLs and none is
 * ever guessed. The dynamic-route form is what lets the file be omitted.
 */
import type { APIRoute, GetStaticPaths } from "astro";
import { canonicalOrigin, canonicalPath } from "../lib/i18n.ts";
import { loadSiteConfig } from "../lib/loadSiteConfig.ts";

export const getStaticPaths = (() =>
  canonicalOrigin(loadSiteConfig()) ? [{ params: { sitemap: "sitemap" } }] : []) satisfies GetStaticPaths;

function escapeXml(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export const GET: APIRoute = () => {
  const siteConfig = loadSiteConfig();
  const origin = canonicalOrigin(siteConfig)!;
  const urls = siteConfig.pages
    .map((page) => `  <url><loc>${escapeXml(`${origin}${canonicalPath(page.path)}`)}</loc></url>`)
    .join("\n");
  const body = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`;
  return new Response(body, { headers: { "Content-Type": "application/xml; charset=utf-8" } });
};
