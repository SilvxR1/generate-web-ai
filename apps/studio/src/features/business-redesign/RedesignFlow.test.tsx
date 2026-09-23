// A8.1: the one primary "redesign this website" workflow. Covers the
// product invariants the task itself calls out explicitly: no raw
// BrandMode/CreativeLevel enum names or provider names in the normal
// path, the A/B choice maps to the right strategy, real content is kept
// by default, Generate/Preview/Approve never publish, Publish is the
// only call that can, and loading states prevent duplicate submissions.
import { exampleReformaValenciaConfig } from "@generate-web-ai/business-config-types";
import { generateSiteConfig } from "@generate-web-ai/website-generator";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CreatedBusiness } from "../../lib/api";
import { RedesignFlow } from "./RedesignFlow";

const TENANT_ID = "11111111-1111-1111-1111-111111111111";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

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

function creativeGeneration(overrides: Record<string, unknown> = {}) {
  return {
    id: "gen-1",
    business_id: "biz-1",
    provider: "internal",
    generation_type: "website",
    creative_level: "basic",
    status: "completed",
    external_reference: null,
    credits_used: null,
    estimated_cost: null,
    started_at: "2026-01-01T00:00:00Z",
    completed_at: "2026-01-01T00:00:05Z",
    error: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function websiteDraft(overrides: Record<string, unknown> = {}) {
  return {
    id: "draft-1",
    business_id: "biz-1",
    creative_generation_id: "gen-1",
    engine: "deterministic",
    site_config: generateSiteConfig(exampleReformaValenciaConfig),
    status: "ready",
    build_error: null,
    validation_issues: null,
    approved_at: null,
    published_at: null,
    published_website_id: null,
    created_at: "2026-01-01T00:00:10Z",
    ...overrides,
  };
}

describe("RedesignFlow", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  const onPublished = vi.fn();
  const onClose = vi.fn();

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    onPublished.mockClear();
    onClose.mockClear();
    // Mount-time availability check (app.routers.creative's own
    // GET .../creative-providers) — every test needs this resolved,
    // regardless of what it exercises afterward.
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, [{ provider: "internal", available: true, capabilities: ["website"], unavailable_reason: null }]),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function renderFlow() {
    return render(
      <RedesignFlow business={business()} tenantId={TENANT_ID} assets={[]} onPublished={onPublished} onClose={onClose} />,
    );
  }

  it("shows plain-language intent choices, never raw BrandMode enum names", async () => {
    renderFlow();

    expect(await screen.findByText("Refresh the current design")).toBeInTheDocument();
    expect(screen.getByText("Create a new design direction")).toBeInTheDocument();
    expect(screen.queryByText(/\bevolve\b/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/new_direction/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\bpreserve\b/i)).not.toBeInTheDocument();
  });

  it("never requires choosing a raw CreativeLevel, and never shows provider names, anywhere in the normal flow", async () => {
    const user = userEvent.setup();
    renderFlow();

    await user.click(await screen.findByText("Refresh the current design"));
    await user.click(screen.getByRole("button", { name: "Continue" }));

    // "premium" legitimately appears as plain language ("AI-generated
    // premium visuals") — the raw CreativeLevel enum value/option is what
    // must never appear, which is what these checks assert.
    expect(screen.queryByText(/\bbasic\b/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\bprofessional\b/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\bcinematic\b/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/higgsfield/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\binternal\b/i)).not.toBeInTheDocument();
  });

  it("communicates that real content is kept by default", async () => {
    const user = userEvent.setup();
    renderFlow();

    await user.click(await screen.findByText("Refresh the current design"));
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(screen.getByText(/Your real business information/)).toBeInTheDocument();
    expect(screen.getByText(/Your real logo/)).toBeInTheDocument();
    expect(screen.getByText(/Your real photographs/)).toBeInTheDocument();
  });

  it('"Refresh the current design" maps to strategy=evolve and level=basic — never a paid provider', async () => {
    const user = userEvent.setup();
    renderFlow();
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { strategy: "evolve", level: "basic", preferred_provider: null }));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, creativeGeneration()));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, websiteDraft()));

    await user.click(await screen.findByText("Refresh the current design"));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Generate proposal" }));

    await waitFor(() => expect(screen.getByText("Proposal preview")).toBeInTheDocument());

    const configCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/creative-config"));
    expect(configCall).toBeDefined();
    const [, init] = configCall as [string, RequestInit];
    const body = JSON.parse(init.body as string);
    expect(body).toEqual({ strategy: "evolve", level: "basic", preferred_provider: null });
  });

  it('"Create a new design direction" maps to strategy=new_direction and level=basic — never a paid provider', async () => {
    const user = userEvent.setup();
    renderFlow();
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, { strategy: "new_direction", level: "basic", preferred_provider: null }),
    );
    fetchMock.mockResolvedValueOnce(jsonResponse(200, creativeGeneration()));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, websiteDraft()));

    await user.click(await screen.findByText("Create a new design direction"));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Generate proposal" }));

    await waitFor(() => expect(screen.getByText("Proposal preview")).toBeInTheDocument());

    const configCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/creative-config"));
    const [, init] = configCall as [string, RequestInit];
    const body = JSON.parse(init.body as string);
    expect(body.strategy).toBe("new_direction");
    expect(body.level).toBe("basic");
  });

  it("Generate proposal never calls publish — the live website is untouched", async () => {
    const user = userEvent.setup();
    renderFlow();
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { strategy: "evolve", level: "basic", preferred_provider: null }));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, creativeGeneration()));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, websiteDraft()));

    await user.click(await screen.findByText("Refresh the current design"));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Generate proposal" }));

    await waitFor(() => expect(screen.getByText("Proposal preview")).toBeInTheDocument());
    expect(screen.getByText(/your live website has not changed/i)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/publish"))).toBe(false);
    expect(onPublished).not.toHaveBeenCalled();
  });

  it("Approve never publishes — Publish remains a separate, explicit action", async () => {
    const user = userEvent.setup();
    renderFlow();
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { strategy: "evolve", level: "basic", preferred_provider: null }));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, creativeGeneration()));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, websiteDraft()));

    await user.click(await screen.findByText("Refresh the current design"));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Generate proposal" }));
    await waitFor(() => expect(screen.getByText("Proposal preview")).toBeInTheDocument());

    fetchMock.mockResolvedValueOnce(jsonResponse(200, websiteDraft({ status: "approved", approved_at: "2026-01-01T00:01:00Z" })));
    await user.click(screen.getByRole("button", { name: "Use this design" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Publish" })).toBeInTheDocument());
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/publish"))).toBe(false);
    expect(onPublished).not.toHaveBeenCalled();
    expect(screen.getByText(/Your current website is still live/)).toBeInTheDocument();
  });

  it("Publish is explicit, calls the publish endpoint exactly once, and reports success", async () => {
    const user = userEvent.setup();
    renderFlow();
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { strategy: "evolve", level: "basic", preferred_provider: null }));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, creativeGeneration()));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, websiteDraft()));

    await user.click(await screen.findByText("Refresh the current design"));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Generate proposal" }));
    await waitFor(() => expect(screen.getByText("Proposal preview")).toBeInTheDocument());

    fetchMock.mockResolvedValueOnce(jsonResponse(200, websiteDraft({ status: "approved", approved_at: "2026-01-01T00:01:00Z" })));
    await user.click(screen.getByRole("button", { name: "Use this design" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Publish" })).toBeInTheDocument());

    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, { status: "live", live_url: "https://example.pages.dev", deployment_id: "d1", deployed_at: "x", updated_at: "x" }),
    );
    await user.click(screen.getByRole("button", { name: "Publish" }));

    await waitFor(() => expect(onPublished).toHaveBeenCalledTimes(1));
    const publishCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes("/publish"));
    expect(publishCalls).toHaveLength(1);
  });

  it("disables Generate proposal while generating, preventing a duplicate submission", async () => {
    const user = userEvent.setup();
    renderFlow();
    let resolveConfig: (value: Response) => void = () => {};
    fetchMock.mockImplementationOnce(
      () => new Promise<Response>((resolve) => { resolveConfig = resolve; }),
    );

    await user.click(await screen.findByText("Refresh the current design"));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    const generateButton = screen.getByRole("button", { name: "Generate proposal" });
    await user.click(generateButton);

    expect(screen.getByRole("button", { name: /Generating proposal/ })).toBeDisabled();

    resolveConfig(jsonResponse(200, { strategy: "evolve", level: "basic", preferred_provider: null }));
  });

  it("disables Publish while publishing, preventing a duplicate submission", async () => {
    const user = userEvent.setup();
    renderFlow();
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { strategy: "evolve", level: "basic", preferred_provider: null }));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, creativeGeneration()));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, websiteDraft()));

    await user.click(await screen.findByText("Refresh the current design"));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Generate proposal" }));
    await waitFor(() => expect(screen.getByText("Proposal preview")).toBeInTheDocument());

    fetchMock.mockResolvedValueOnce(jsonResponse(200, websiteDraft({ status: "approved", approved_at: "x" })));
    await user.click(screen.getByRole("button", { name: "Use this design" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Publish" })).toBeInTheDocument());

    let resolvePublish: (value: Response) => void = () => {};
    fetchMock.mockImplementationOnce(() => new Promise<Response>((resolve) => { resolvePublish = resolve; }));
    await user.click(screen.getByRole("button", { name: "Publish" }));

    expect(screen.getByRole("button", { name: /Publishing/ })).toBeDisabled();

    resolvePublish(
      jsonResponse(200, { status: "live", live_url: "https://example.pages.dev", deployment_id: "d1", deployed_at: "x", updated_at: "x" }),
    );
  });

  it("a build failure clearly states the live website was not changed, in plain language", async () => {
    const user = userEvent.setup();
    renderFlow();
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { strategy: "evolve", level: "basic", preferred_provider: null }));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, creativeGeneration({ status: "failed", error: "internal build error" })));

    await user.click(await screen.findByText("Refresh the current design"));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Generate proposal" }));

    expect(await screen.findByText(/your live website has not changed/i)).toBeInTheDocument();
    // Never a raw backend error code/status leaked into the primary UX.
    expect(screen.queryByText(/500|internal build error|traceback/i)).not.toBeInTheDocument();
  });
});
