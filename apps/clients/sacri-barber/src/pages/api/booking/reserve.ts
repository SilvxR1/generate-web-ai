export const prerender = false;

import type { APIRoute } from "astro";
import { env } from "cloudflare:workers";
import { reserveSlot } from "../../../lib/booking/db";

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const TIME_RE = /^\d{2}:\d{2}$/;

interface ReserveBody {
  serviceId?: string;
  date?: string;
  time?: string;
  name?: string;
  phone?: string;
  email?: string;
  notes?: string;
  /** Honeypot: a field named plausibly ("website"), hidden from sighted,
   * keyboard, and screen-reader users via BookingCalendar.astro's markup
   * and CSS, but visible to naive bots that fill in every field they find.
   * A non-empty value here means the request almost certainly isn't human. */
  website?: string;
}

function json(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

export const POST: APIRoute = async ({ request }) => {
  let body: ReserveBody;
  try {
    body = await request.json();
  } catch {
    return json({ error: "Solicitud inválida." }, 400);
  }

  // Honeypot triggered: return a normal-looking success so the bot has no
  // signal to adapt on, but never touch the database.
  if (body.website) {
    return json({ ok: true }, 201);
  }

  const { serviceId, date, time, name, phone, email, notes } = body;
  if (
    !serviceId ||
    !date ||
    !time ||
    !name?.trim() ||
    !phone?.trim() ||
    !DATE_RE.test(date) ||
    !TIME_RE.test(time)
  ) {
    return json({ error: "Faltan datos obligatorios." }, 400);
  }

  const outcome = await reserveSlot(env.DB, {
    serviceId,
    date,
    time,
    name: name.trim(),
    phone: phone.trim(),
    email: email?.trim() || undefined,
    notes: notes?.trim() || undefined,
  });

  if (!outcome.ok) {
    if (outcome.reason === "conflict") {
      return json({ error: "Esa hora ya no está disponible. Elige otra." }, 409);
    }
    return json({ error: "Servicio no válido." }, 400);
  }

  return json({ ok: true, id: outcome.id }, 201);
};
