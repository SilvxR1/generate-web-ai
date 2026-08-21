// D1 query helpers for the real booking system. Deliberately app-local (not
// a shared package) — see docs/architecture.md and the architecture plan
// for why: sacri-barber is a test client, and this would be the first
// package in the repo with real runtime/server logic. Promote to
// packages/booking once a second real client needs appointment booking.
//
// Business hours are read from src/config/site.ts's `business.openingHours`
// (single source of truth) rather than duplicated here — only which
// *weekdays* are open needs mirroring below (Tue-Sat), same as the mock
// prototype this replaces (src/data/appointments.ts, now removed) did.
import type { BookingDayConfig, BookingServiceConfig, BookingSlotConfig } from "@generate-web-ai/site-config";

const CLOSED_WEEKDAYS = new Set([0, 1]); // JS getDay(): 0=Sunday, 1=Monday
const OPEN_MINUTES = 10 * 60;
const CLOSE_MINUTES = 20 * 60;
const SLOT_MINUTES = 45;

function toISODate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/** The next `count` calendar days starting today. Pure/no DB access — "is this
 * weekday open at all" never depends on stored data. Display formatting
 * (weekday/day/month labels) is a client-side concern — see
 * BookingCalendar.astro's script — not baked into this response. */
export function listUpcomingDays(count = 14, from: Date = new Date()): BookingDayConfig[] {
  const days: BookingDayConfig[] = [];
  for (let i = 0; i < count; i++) {
    const date = new Date(from.getFullYear(), from.getMonth(), from.getDate() + i);
    days.push({
      dateISO: toISODate(date),
      isOpen: !CLOSED_WEEKDAYS.has(date.getDay()),
    });
  }
  return days;
}

function fullDaySlotGrid(): string[] {
  const times: string[] = [];
  for (let minutes = OPEN_MINUTES; minutes < CLOSE_MINUTES; minutes += SLOT_MINUTES) {
    const h = String(Math.floor(minutes / 60)).padStart(2, "0");
    const m = String(minutes % 60).padStart(2, "0");
    times.push(`${h}:${m}`);
  }
  return times;
}

export async function getActiveServices(db: D1Database): Promise<BookingServiceConfig[]> {
  const { results } = await db
    .prepare(
      "SELECT id, name, duration_minutes AS durationMinutes, price_cents AS priceCents FROM services WHERE active = 1 ORDER BY rowid",
    )
    .all<BookingServiceConfig>();
  return results;
}

/** Real availability for one date: the shop's fixed slot grid minus whatever
 * is already booked or blacked out. Returns `[]` for closed weekdays and
 * blackout dates alike — an empty grid, not an error, same as "no slots
 * happened to be free." */
export async function getSlotsForDate(db: D1Database, dateISO: string): Promise<BookingSlotConfig[]> {
  const weekday = new Date(`${dateISO}T00:00:00`).getDay();
  if (CLOSED_WEEKDAYS.has(weekday)) return [];

  const blackout = await db.prepare("SELECT 1 FROM blackout_dates WHERE date = ?").bind(dateISO).first();
  if (blackout) return [];

  const { results: booked } = await db
    .prepare("SELECT starts_at FROM appointments WHERE status = 'confirmed' AND starts_at LIKE ?")
    .bind(`${dateISO}T%`)
    .all<{ starts_at: string }>();
  const bookedTimes = new Set(booked.map((row) => row.starts_at.slice(11, 16)));

  return fullDaySlotGrid().map((time) => ({ time, available: !bookedTimes.has(time) }));
}

export type ReserveOutcome = { ok: true; id: number } | { ok: false; reason: "conflict" | "invalid_service" };

/** Attempts to reserve a slot. The `UNIQUE(starts_at)` constraint (not a
 * check-then-insert) is what actually prevents double-booking under
 * concurrent requests — see migrations/0001_init.sql. */
export async function reserveSlot(
  db: D1Database,
  input: { serviceId: string; date: string; time: string; name: string; phone: string; email?: string; notes?: string },
): Promise<ReserveOutcome> {
  const service = await db
    .prepare("SELECT duration_minutes AS durationMinutes FROM services WHERE id = ? AND active = 1")
    .bind(input.serviceId)
    .first<{ durationMinutes: number }>();
  if (!service) return { ok: false, reason: "invalid_service" };

  const startsAt = `${input.date}T${input.time}:00`;

  try {
    const result = await db
      .prepare(
        `INSERT INTO appointments (service_id, starts_at, duration_minutes, customer_name, customer_phone, customer_email, notes)
         VALUES (?, ?, ?, ?, ?, ?, ?)`,
      )
      .bind(input.serviceId, startsAt, service.durationMinutes, input.name, input.phone, input.email ?? null, input.notes ?? null)
      .run();
    return { ok: true, id: Number(result.meta.last_row_id) };
  } catch (error) {
    if (error instanceof Error && /UNIQUE constraint failed/i.test(error.message)) {
      return { ok: false, reason: "conflict" };
    }
    throw error;
  }
}
