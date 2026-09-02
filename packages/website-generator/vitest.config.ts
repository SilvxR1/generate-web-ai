// Only needed so scripts/validate-generated-site.test.ts can import a
// real .astro component (PageRenderer) and render it via Astro's
// Container API — that requires Vite's Astro transform, which plain
// `node`/tsx can't provide. getViteConfig is Astro's own documented way
// to get that inside Vitest without hand-rolling a Vite server.
import { getViteConfig } from "astro/config";

export default getViteConfig({});
