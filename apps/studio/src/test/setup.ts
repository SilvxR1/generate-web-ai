import { cleanup } from "@testing-library/react";
import { afterAll, afterEach } from "vitest";
import "@testing-library/jest-dom/vitest";
import { installNetworkGuard, takeBlockedRequests } from "./networkGuard";

// Fail closed: no test may reach a real API (see ./networkGuard). Must run
// before any test stubs `fetch`, so vi.unstubAllGlobals() restores the
// guard rather than the real network.
installNetworkGuard();

function failOnBlockedRequests(): void {
  const requests = takeBlockedRequests();
  if (requests.length > 0) {
    throw new Error(
      "Unmocked network request(s) were blocked — mock them, or await the async work that makes them before the " +
        `test ends:\n${requests.map((r) => `  ${r.api} ${r.method} ${r.url}`).join("\n")}`,
    );
  }
}

// Explicit (not vitest's `globals: true`) test files mean
// @testing-library/react's own auto-cleanup — which detects a global
// `afterEach` — never registers. Do it here instead, once, for every
// test file.
afterEach(() => {
  cleanup();
  failOnBlockedRequests();
});

// Work that outlives the file's last test still fails the file.
afterAll(() => {
  failOnBlockedRequests();
});
