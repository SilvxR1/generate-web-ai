import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    // Never a developer's .env.local API (which may be production): tests
    // always see a non-routable origin (.invalid is reserved, RFC 2606),
    // and src/test/networkGuard.ts blocks any request that isn't mocked.
    env: { VITE_API_URL: "http://api.test.invalid" },
    // afterEach hooks run in registration order, so src/test/setup.ts's
    // cleanup() unmounts every component BEFORE a test file's own
    // afterEach restores globals (vi.unstubAllGlobals) — no still-mounted
    // effect can fetch in between.
    sequence: { hooks: "list" },
  },
});
