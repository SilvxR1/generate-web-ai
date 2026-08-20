// Sacri Barber — mocked appointment data for the booking-calendar prototype
// in src/components/BookingCalendar.astro. Phase-2 prototype only: no
// backend, no persistence. Deliberately local to this client app, not
// packages/blocks — see the component's own doc comment for why.
//
// Dates are computed relative to the visitor's local "now", not at build
// time: this site builds as static output, so anything computed in an
// .astro file's frontmatter is frozen at build time, not per-visit. A
// "next 14 days" calendar has to be real client-side JavaScript to stay
// correct between rebuilds.

export interface DayOption {
  /** ISO date, "YYYY-MM-DD". */
  dateISO: string;
  weekdayShort: string;
  dayNumber: number;
  monthShort: string;
  isOpen: boolean;
}

export interface TimeSlot {
  time: string;
  available: boolean;
}

export const SERVICE_OPTIONS = [
  { value: "corte-clasico", label: "Corte clásico" },
  { value: "corte-barba", label: "Corte + barba" },
  { value: "afeitado-navaja", label: "Afeitado a navaja" },
  { value: "arreglo-barba", label: "Arreglo de barba" },
  { value: "diseno-barba", label: "Diseño de barba" },
  { value: "coloracion", label: "Coloración y cuidado" },
] as const;

// Mirrors the shop's real hours in src/config/site.ts's
// `business.openingHours` (Tue-Sat, 10:00-20:00) — JS getDay(): 0=Sunday.
const CLOSED_WEEKDAYS = new Set([0, 1]);
const OPEN_MINUTES = 10 * 60;
const CLOSE_MINUTES = 20 * 60;
const SLOT_MINUTES = 45;

const WEEKDAY_LABELS = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
const MONTH_LABELS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

function toISODate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/** The next `count` calendar days starting today, in the visitor's local time. */
export function getUpcomingDays(count = 14, from: Date = new Date()): DayOption[] {
  const days: DayOption[] = [];
  for (let i = 0; i < count; i++) {
    const date = new Date(from.getFullYear(), from.getMonth(), from.getDate() + i);
    days.push({
      dateISO: toISODate(date),
      // `getDay()`/`getMonth()` are always in-range for these fixed-length
      // lookup tables (0-6 and 0-11 respectively), so the indexed access is
      // safe despite `noUncheckedIndexedAccess`.
      weekdayShort: WEEKDAY_LABELS[date.getDay()]!,
      dayNumber: date.getDate(),
      monthShort: MONTH_LABELS[date.getMonth()]!,
      isOpen: !CLOSED_WEEKDAYS.has(date.getDay()),
    });
  }
  return days;
}

/**
 * Small deterministic hash of date+time — used to mark a stable-but-varied
 * subset of slots as already booked. Deliberately not `Math.random()`: a
 * mocked slot that's "available" one reload and "booked" the next would
 * read as broken, not as a believable calendar.
 */
function hashSlot(dateISO: string, time: string): number {
  const input = `${dateISO}T${time}`;
  let hash = 0;
  for (let i = 0; i < input.length; i++) {
    hash = (Math.imul(hash, 31) + input.charCodeAt(i)) >>> 0;
  }
  return hash;
}

/** Time slots for one day, with a deterministic subset marked unavailable. */
export function getTimeSlots(dateISO: string): TimeSlot[] {
  const slots: TimeSlot[] = [];
  for (let minutes = OPEN_MINUTES; minutes < CLOSE_MINUTES; minutes += SLOT_MINUTES) {
    const h = String(Math.floor(minutes / 60)).padStart(2, "0");
    const m = String(minutes % 60).padStart(2, "0");
    const time = `${h}:${m}`;
    slots.push({ time, available: hashSlot(dateISO, time) % 3 !== 0 });
  }
  return slots;
}
