// Shared vocabulary for a client's real (D1-backed) appointment-booking
// feature. Types only — no D1/Cloudflare/runtime dependency, matching this
// package's role as the zero-runtime "data a client site is described as"
// layer. The actual D1 queries, API routes, and UI live in the client app
// that needs booking (see apps/clients/sacri-barber/src/lib/booking) until a
// second real client needs it and the implementation is worth promoting to
// a shared package — see docs/architecture.md's note on this decision.

export interface BookingServiceConfig {
  /** Slug, e.g. "corte-clasico" — primary key in the `services` D1 table. */
  id: string;
  name: string;
  durationMinutes: number;
  priceCents: number;
}

export interface BookingDayConfig {
  /** ISO date, "YYYY-MM-DD". */
  dateISO: string;
  isOpen: boolean;
}

export interface BookingSlotConfig {
  /** 24h "HH:MM". */
  time: string;
  available: boolean;
}

export interface BookingReservationInput {
  serviceId: string;
  date: string;
  time: string;
  name: string;
  phone: string;
  email?: string;
  notes?: string;
}
