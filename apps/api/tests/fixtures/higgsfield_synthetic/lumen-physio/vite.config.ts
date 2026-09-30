import { tanstackStart } from "@tanstack/react-start/plugin/vite";
import viteReact from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The builder's server bundle runs on Cloudflare Workers: its runtime
// module is provided by the platform, never bundled.
export default defineConfig({
  ssr: { external: ["cloudflare:workers"] },
  build: { rollupOptions: { external: [/^cloudflare:/] } },
  plugins: [tanstackStart({ srcDirectory: "src" }), viteReact()],
});
