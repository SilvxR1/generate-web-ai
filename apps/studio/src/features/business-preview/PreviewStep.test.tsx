// A8.3.4.2b: the first-site flow publishes straight from SiteConfig — it
// has no WebsiteDraft, so no real preview exists here (tracked as
// A8_ARTIFACT_PROMOTION_FOLLOWUP). It must describe the React summary as a
// content review, never claim a website preview.
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

  it("labels its summary as site content to review and never offers or claims a real preview", async () => {
    render(<PreviewStep business={business()} tenantId="t-1" justCreated={false} onEdit={vi.fn()} onCreateAnother={vi.fn()} />);

    expect(await screen.findByRole("heading", { name: "Review site content" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Website preview" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /real preview/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/Open real preview/)).not.toBeInTheDocument();
  });
});
