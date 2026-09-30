// H1.2: a lead's additional site-form fields (service, surface area, ...)
// are visible in Studio as plain text, and leads without them render as before.
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Lead } from "../../lib/api";
import { LeadsList } from "./LeadsList";

function lead(overrides: Partial<Lead> = {}): Lead {
  return {
    id: "lead-1",
    business_id: "biz-1",
    source: "website_form",
    name: "Prueba H1",
    email: "prueba@example.com",
    phone: "600000000",
    message: "Reformar la cocina completa",
    subject: "Cocina",
    source_url: "https://nexo-reformas.example/",
    consent_given: false,
    status: "new",
    acknowledgement_status: "not_configured",
    created_at: "2026-09-30T10:00:00Z",
    ...overrides,
  };
}

function renderList(leads: Lead[]) {
  return render(
    <LeadsList
      leads={leads}
      isLoading={false}
      error={null}
      businessId="biz-1"
      tenantId="tenant-1"
      filters={{}}
      onFiltersChange={vi.fn()}
      onUpdateStatus={vi.fn()}
    />,
  );
}

describe("LeadsList form details", () => {
  it("shows every form detail with the label the visitor saw", () => {
    renderList([
      lead({
        details: [
          { key: "service", label: "Tipo de reforma", value: "Cocina" },
          { key: "surface_area", label: "Superficie aproximada", value: "80" },
        ],
      }),
    ]);
    const details = screen.getByLabelText("Form details");
    expect(within(details).getByText("Tipo de reforma")).toBeTruthy();
    expect(within(details).getByText("Cocina")).toBeTruthy();
    expect(within(details).getByText("Superficie aproximada")).toBeTruthy();
    expect(within(details).getByText("80")).toBeTruthy();
  });

  it("renders submitted values as text, never as markup", () => {
    renderList([lead({ details: [{ key: "notes", label: "Notas", value: "<img src=x onerror=alert(1)>" }] })]);
    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeTruthy();
    expect(document.querySelector("img")).toBeNull();
  });

  it("renders a lead without details exactly as before", () => {
    renderList([lead({ details: null }), lead({ id: "lead-2", details: undefined })]);
    expect(screen.queryByLabelText("Form details")).toBeNull();
    expect(screen.getAllByText("Prueba H1")).toHaveLength(2);
  });
});
