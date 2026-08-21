/// <reference types="astro/client" />

// Minimal, hand-written D1 typings for exactly the surface
// src/lib/booking/db.ts uses — deliberately NOT `@cloudflare/workers-types`.
// That package has zero exports (every declaration is a bare global) and
// bundles the full workerd runtime globals (Response, DOMException,
// ReadableStream, ...), which conflict with the browser DOM lib that
// BookingCalendar.astro's client-side `<script>` needs — `astro check`
// type-checks the whole project (client scripts included) as one program,
// so there's no way to scope that package to "just the server files."
// `skipLibCheck` (set in packages/config/tsconfig.base.json) means this
// file's own internal correctness isn't strictly re-verified, but it only
// needs to describe the shape our code actually calls: prepare/bind/
// first/run/all.
interface D1Result<T = unknown> {
  results: T[];
  meta: {
    last_row_id: number;
    changes: number;
    duration: number;
  };
}

interface D1PreparedStatement {
  bind(...values: unknown[]): D1PreparedStatement;
  first<T = unknown>(): Promise<T | null>;
  run(): Promise<D1Result>;
  all<T = unknown>(): Promise<D1Result<T>>;
}

interface D1Database {
  prepare(query: string): D1PreparedStatement;
}

declare module "cloudflare:workers" {
  export const env: { DB: D1Database };
}
