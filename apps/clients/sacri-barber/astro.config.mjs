import { defineConfig } from "astro/config";
import cloudflare from "@astrojs/cloudflare";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  site: "https://sacribarber.example",
  // Fixed dev-server port so this app and apps/clients/reforma-casa-valencia
  // (which uses Astro's default 4321) can run locally at the same time.
  server: {
    port: 4322,
  },
  // The booking feature (src/pages/api/booking/*) needs a real backend (D1)
  // to check/reserve appointments, so this app needs the Cloudflare adapter.
  // `output` stays at Astro's default ("static"): the marketing pages keep
  // prerendering exactly as before, and only the two booking API routes
  // opt into on-demand rendering via their own `export const prerender =
  // false` — see those files for why. reforma-casa-valencia has no such
  // feature and deliberately has no adapter at all.
  adapter: cloudflare(),
  vite: {
    plugins: [tailwindcss()],
  },
});
