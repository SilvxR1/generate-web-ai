// Tests must never contact a real API. Every test that needs the backend
// stubs `fetch` itself (vi.stubGlobal); anything that slips past those
// stubs — a missing or exhausted mock, or async work that outlives its test
// after vi.unstubAllGlobals() — lands here instead of the network.
//
// Installed by plain assignment BEFORE any test runs, so it is also what
// vi.unstubAllGlobals() restores (it restores the value that existed before
// the first stubGlobal), never jsdom/Node's real implementation.
//
// Blocked requests are rejected (the app sees an ordinary network failure)
// and recorded; src/test/setup.ts fails the test file if any were recorded.

export interface BlockedRequest {
  api: "fetch" | "XMLHttpRequest" | "WebSocket";
  method: string;
  url: string;
}

const blocked: BlockedRequest[] = [];

function block(request: BlockedRequest): Error {
  blocked.push(request);
  return new Error(`Blocked unmocked ${request.api} ${request.method} ${request.url} — tests must never reach a real API.`);
}

/** Returns and clears the requests blocked so far. */
export function takeBlockedRequests(): BlockedRequest[] {
  return blocked.splice(0, blocked.length);
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.href;
  return input.url;
}

export function installNetworkGuard(): void {
  globalThis.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
    return Promise.reject(new TypeError(block({ api: "fetch", method, url: requestUrl(input) }).message));
  };

  class BlockedXMLHttpRequest extends XMLHttpRequest {
    #method = "GET";
    #url = "";

    override open(method: string, url: string | URL): void {
      this.#method = method.toUpperCase();
      this.#url = String(url);
    }

    override send(): void {
      throw block({ api: "XMLHttpRequest", method: this.#method, url: this.#url });
    }
  }
  globalThis.XMLHttpRequest = BlockedXMLHttpRequest;

  globalThis.WebSocket = class {
    constructor(url: string | URL) {
      throw block({ api: "WebSocket", method: "CONNECT", url: String(url) });
    }
  } as unknown as typeof WebSocket;
}
