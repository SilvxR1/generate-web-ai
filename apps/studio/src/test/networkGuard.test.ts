// Regression: an unmocked request made by app code during a test — here
// the exact class that escaped to production (POST
// /businesses/biz-1/website-drafts after vi.unstubAllGlobals() restored
// "real" fetch) — is blocked deterministically and never reaches a network,
// and the API base is never a developer's .env.local value.
import { afterEach, describe, expect, it, vi } from "vitest";
import { API_URL, NetworkError, createWebsiteDraft } from "../lib/api";
import { takeBlockedRequests } from "./networkGuard";

describe("test network isolation", () => {
  afterEach(() => {
    // These tests trigger blocked requests on purpose; don't let setup.ts
    // fail them for it.
    takeBlockedRequests();
  });

  it("tests always use the non-routable test API origin, never .env.local's", () => {
    expect(API_URL).toBe("http://api.test.invalid");
  });

  it("after vi.unstubAllGlobals(), fetch is the guard — an escaped draft request is blocked, not sent", async () => {
    vi.stubGlobal("fetch", vi.fn());
    vi.unstubAllGlobals();

    const siteConfig = {} as Parameters<typeof createWebsiteDraft>[1];
    await expect(createWebsiteDraft("biz-1", siteConfig, null, "tenant-1")).rejects.toBeInstanceOf(NetworkError);

    expect(takeBlockedRequests()).toEqual([
      { api: "fetch", method: "POST", url: "http://api.test.invalid/businesses/biz-1/website-drafts" },
    ]);
  });

  it("blocks even an absolute, non-mocked URL", async () => {
    await expect(fetch("https://production-api.example.invalid/health")).rejects.toThrow(/Blocked unmocked fetch/);
    expect(takeBlockedRequests()).toHaveLength(1);
  });

  it("blocks XMLHttpRequest and WebSocket too", () => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "https://example.com/x");
    expect(() => xhr.send()).toThrow(/Blocked unmocked XMLHttpRequest POST/);
    expect(() => new WebSocket("wss://example.com/socket")).toThrow(/Blocked unmocked WebSocket/);
    expect(takeBlockedRequests()).toHaveLength(2);
  });
});
