/**
 * C2.1: a real robots.txt (previously the Pages SPA fallback served the
 * homepage HTML here). Everything is crawlable on the canonical host; the
 * default *.pages.dev host is kept out of indexes by an X-Robots-Tag rule
 * in the generated _headers file instead (app.publishing.security_headers),
 * because this one artifact is served on every host.
 */
import type { APIRoute } from "astro";
import { canonicalOrigin } from "../lib/i18n.ts";
import { loadSiteConfig } from "../lib/loadSiteConfig.ts";

export const GET: APIRoute = () => {
  const origin = canonicalOrigin(loadSiteConfig());
  const lines = ["User-agent: *", "Allow: /", ...(origin ? ["", `Sitemap: ${origin}/sitemap.xml`] : [])];
  return new Response(`${lines.join("\n")}\n`, { headers: { "Content-Type": "text/plain; charset=utf-8" } });
};
