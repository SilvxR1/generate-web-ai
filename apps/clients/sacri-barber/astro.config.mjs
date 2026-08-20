import { defineConfig } from "astro/config";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  site: "https://sacribarber.example",
  // Fixed dev-server port so this app and apps/clients/reforma-casa-valencia
  // (which uses Astro's default 4321) can run locally at the same time.
  server: {
    port: 4322,
  },
  vite: {
    plugins: [tailwindcss()],
  },
});
