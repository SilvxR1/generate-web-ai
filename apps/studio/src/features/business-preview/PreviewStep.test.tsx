// A8.4: the first-site flow goes live through the WebsiteDraft lifecycle
// (Generate website -> Open real preview -> Use this design -> Publish).
// The React SiteConfig summary is only a secondary "Content summary" —
// never called the website preview — and no direct publish is offered.
import { exampleReformaValenciaConfig } from "@generate-web-ai/business-config-types";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CreatedBusiness } from "../../lib/api";
import { PreviewStep } from "./PreviewStep";

function business(): CreatedBusiness {
  return {
    id: "biz-1",
    name: exampleReformaValenciaConfig.business_profile.name,
    slug: exampleReformaValenciaConfig.business_profile.slug,
    status: "active",
    raw_description: "A real reform company in Valencia.",
    config: exampleReformaValenciaConfig,
  };
}

describe("PreviewStep (first-site flow)", () => {
  beforeEach(() => {
    // Every panel's fetch fails: only the static wording matters here.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ error: { code: "not_found", message: "x" } }), { status: 404 })),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("offers Generate website (not a direct publish) and a secondary Content summary, never a 'Website preview'", async () => {
    render(<PreviewStep business={business()} tenantId="t-1" justCreated={false} onEdit={vi.fn()} onCreateAnother={vi.fn()} />);

    expect(await screen.findByRole("heading", { name: "Website" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Generate website" })).toBeInTheDocument();
    expect(screen.getByText("Content summary", { selector: "summary" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Website preview" })).not.toBeInTheDocument();
    // No draft yet: nothing to preview, approve or publish.
    expect(screen.queryByRole("button", { name: /real preview/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Publish/ })).not.toBeInTheDocument();
  });
});
