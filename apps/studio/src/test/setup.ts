import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import "@testing-library/jest-dom/vitest";

// Explicit (not vitest's `globals: true`) test files mean
// @testing-library/react's own auto-cleanup — which detects a global
// `afterEach` — never registers. Do it here instead, once, for every
// test file.
afterEach(() => {
  cleanup();
});
