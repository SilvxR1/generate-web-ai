-- Initial schema for the real (D1-backed) booking system. Deliberately
-- minimal for a single-location, single-chair test client — see the
-- architecture plan for what's intentionally NOT modeled yet (multiple
-- chairs/barbers, variable-duration overlap checking, multi-timezone).

CREATE TABLE services (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  duration_minutes INTEGER NOT NULL,
  price_cents INTEGER NOT NULL,
  active INTEGER NOT NULL DEFAULT 1
);

-- `UNIQUE (starts_at)` is the actual double-booking guard: this table
-- models one chair, so two appointments can never share a start time. A
-- racing second INSERT for the same slot fails this constraint instead of
-- silently creating a duplicate — see src/lib/booking/db.ts's `reserveSlot`
-- for how the resulting SQLITE_CONSTRAINT error becomes a 409 response.
CREATE TABLE appointments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  service_id TEXT NOT NULL REFERENCES services(id),
  starts_at TEXT NOT NULL,
  duration_minutes INTEGER NOT NULL,
  customer_name TEXT NOT NULL,
  customer_phone TEXT NOT NULL,
  customer_email TEXT,
  notes TEXT,
  status TEXT NOT NULL DEFAULT 'confirmed',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (starts_at)
);

CREATE INDEX idx_appointments_starts_at ON appointments (starts_at);

-- Holidays / time off. Optional in practice (empty table is a no-op), cheap
-- to have from day one rather than retrofitting later.
CREATE TABLE blackout_dates (
  date TEXT PRIMARY KEY,
  reason TEXT
);

-- Seed data: mirrors today's SERVICE_OPTIONS (src/data/appointments.ts) and
-- the prices already shown in the Services block content in site.ts. All
-- durations are the shop's one fixed 45-minute grid slot (see db.ts) — a
-- service that logically needs two slots is a known, documented limitation
-- of this MVP, not modeled here.
INSERT INTO services (id, name, duration_minutes, price_cents) VALUES
  ('corte-clasico', 'Corte clásico', 45, 1500),
  ('corte-barba', 'Corte + barba', 45, 2500),
  ('afeitado-navaja', 'Afeitado a navaja', 45, 1800),
  ('arreglo-barba', 'Arreglo de barba', 45, 1200),
  ('diseno-barba', 'Diseño de barba', 45, 1500),
  ('coloracion', 'Coloración y cuidado', 45, 2000);
