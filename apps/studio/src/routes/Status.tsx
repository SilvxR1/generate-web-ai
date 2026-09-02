import { useEffect, useState } from "react";
import { API_URL } from "../lib/api";

interface HealthResponse {
  status: string;
  service: string;
  version: string;
  environment: string;
  timestamp: string;
  uptime_seconds: number;
  dependencies: {
    database: { status: string; detail?: string };
  };
}

type LoadState = { kind: "loading" } | { kind: "error"; message: string } | { kind: "loaded"; data: HealthResponse };

export function Status() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function loadHealth() {
      try {
        const response = await fetch(`${API_URL}/health`);
        const data = (await response.json()) as HealthResponse;
        if (!cancelled) setState({ kind: "loaded", data });
      } catch (error) {
        if (!cancelled) {
          setState({ kind: "error", message: error instanceof Error ? error.message : "Unknown error" });
        }
      }
    }

    void loadHealth();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section>
      <h1>System Status</h1>
      <p>
        Live result of <code>GET {API_URL}/health</code>.
      </p>

      {state.kind === "loading" && <p>Checking...</p>}

      {state.kind === "error" && (
        <p className="status-panel status-panel--error">
          Could not reach the backend: {state.message}. Is it running at {API_URL}?
        </p>
      )}

      {state.kind === "loaded" && (
        <dl className={`status-panel status-panel--${state.data.status === "ok" ? "ok" : "degraded"}`}>
          <dt>Overall status</dt>
          <dd>{state.data.status}</dd>
          <dt>Service</dt>
          <dd>
            {state.data.service} v{state.data.version} ({state.data.environment})
          </dd>
          <dt>Database</dt>
          <dd>
            {state.data.dependencies.database.status}
            {state.data.dependencies.database.detail ? ` — ${state.data.dependencies.database.detail}` : ""}
          </dd>
          <dt>Uptime</dt>
          <dd>{state.data.uptime_seconds.toFixed(1)}s</dd>
          <dt>Checked at</dt>
          <dd>{state.data.timestamp}</dd>
        </dl>
      )}
    </section>
  );
}
