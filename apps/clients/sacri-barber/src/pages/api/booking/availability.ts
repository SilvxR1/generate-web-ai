// Real availability, computed per-request against D1 — replaces the old
// mock's deterministic hash (src/data/appointments.ts, now removed). The
// rest of the site stays static; this route alone opts into on-demand
// (Workers) rendering so it can read the D1 binding.
export const prerender = false;

import type { APIRoute } from "astro";
import { env } from "cloudflare:workers";
import { getActiveServices, getSlotsForDate, listUpcomingDays } from "../../../lib/booking/db";

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

export const GET: APIRoute = async ({ url }) => {
  const date = url.searchParams.get("date");

  if (date !== null) {
    if (!DATE_RE.test(date)) {
      return json({ error: "Fecha inválida." }, 400);
    }
    const slots = await getSlotsForDate(env.DB, date);
    return json({ date, slots });
  }

  const [days, services] = await Promise.all([Promise.resolve(listUpcomingDays(14)), getActiveServices(env.DB)]);
  return json({ days, services });
};
