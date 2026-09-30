import { env } from "cloudflare:workers";

// Builder backend: its own D1 database binding.
export const db = () => (env as unknown as { DB: unknown }).DB;
