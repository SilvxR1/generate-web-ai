// A8.1 (hardened): the one primary "redesign this website" workflow.
// Covers the product invariants the task itself calls out explicitly: no
// raw BrandMode/CreativeLevel enum names or provider names in the normal
// path, the A/B choice maps to the right strategy AS A PER-REQUEST
// OVERRIDE (never a persistent CreativeConfig mutation), no non-functional
// free-text style input, real content (name/logo/photos) genuinely flows
// into the generated proposal, Generate/Preview/Approve never publish,
// Publish is the only call that can, and loading states prevent duplicate
// submissions.
import { exampleReformaValenciaConfig } from "@generate-web-ai/business-config-types";
import { generateSiteConfig } from "@generate-web-ai/website-generator";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { BusinessAsset, CreatedBusiness } from "../../lib/api";
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

function asset(overrides: Partial<BusinessAsset> = {}): BusinessAsset {
  return {
    id: "asset-1",
    business_id: "biz-1",
    kind: "image",
    category: "gallery",
    origin: "uploaded",
    storage_url: "https://cdn.example.com/asset.jpg",
    storage_provider: "r2",
    storage_key: "asset.jpg",
    unavailable_reason: null,
    original_filename: "asset.jpg",
    alt_text: null,
    generation_id: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
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
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function renderFlow(assets: BusinessAsset[] = []) {
    return render(
      <RedesignFlow business={business()} tenantId={TENANT_ID} assets={assets} onPublished={onPublished} onClose={onClose} />,
    );
  }

  async function goToConfirmStep(user: ReturnType<typeof userEvent.setup>, label = "Refresh the current design") {
    await user.click(await screen.findByText(label));
    await user.click(screen.getByRole("button", { name: "Continue" }));
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

    await goToConfirmStep(user);

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

    await goToConfirmStep(user);

    expect(screen.getByText(/Your real business information/)).toBeInTheDocument();
    expect(screen.getByText(/Your real logo/)).toBeInTheDocument();
    expect(screen.getByText(/Your real photographs/)).toBeInTheDocument();
  });

  it("never offers a free-text style input — build_creative_brief has no field that would consume it", async () => {
    const user = userEvent.setup();
    renderFlow();

    await goToConfirmStep(user);

    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/modern, minimal, premium/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/describe the style/i)).not.toBeInTheDocument();
  });

  it('"Refresh the current design" sends brand_strategy=evolve and creative_level=basic as PER-REQUEST overrides, and never calls creative-config', async () => {
    const user = userEvent.setup();
    renderFlow();
    fetchMock.mockResolvedValueOnce(jsonResponse(200, creativeGeneration()));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, websiteDraft()));

    await goToConfirmStep(user, "Refresh the current design");
    await user.click(screen.getByRole("button", { name: "Generate proposal" }));

    await waitFor(() => expect(screen.getByText("Proposal preview")).toBeInTheDocument());

    const generationCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/creative-generations"));
    expect(generationCall).toBeDefined();
    const [, init] = generationCall as [string, RequestInit];
    const body = JSON.parse(init.body as string);
    expect(body).toEqual({ generation_type: "website", brand_strategy: "evolve", creative_level: "basic" });

    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/creative-config"))).toBe(false);
  });

  it('"Create a new design direction" sends brand_strategy=new_direction and creative_level=basic, and never calls creative-config', async () => {
    const user = userEvent.setup();
    renderFlow();
    fetchMock.mockResolvedValueOnce(jsonResponse(200, creativeGeneration()));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, websiteDraft()));

    await goToConfirmStep(user, "Create a new design direction");
    await user.click(screen.getByRole("button", { name: "Generate proposal" }));

    await waitFor(() => expect(screen.getByText("Proposal preview")).toBeInTheDocument());

    const generationCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/creative-generations"));
    const [, init] = generationCall as [string, RequestInit];
    const body = JSON.parse(init.body as string);
    expect(body.brand_strategy).toBe("new_direction");
    expect(body.creative_level).toBe("basic");

    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/creative-config"))).toBe(false);
  });

  it("the generated proposal's site config genuinely carries the business's real name, logo, and photographs — not just UI copy claiming so", async () => {
    const user = userEvent.setup();
    const realLogo = asset({ id: "logo-1", kind: "logo", category: "logo", storage_url: "https://cdn.example.com/real-logo.png" });
    const realPhoto = asset({ id: "photo-1", kind: "image", category: "gallery", storage_url: "https://cdn.example.com/real-photo.jpg" });
    renderFlow([realLogo, realPhoto]);
    fetchMock.mockResolvedValueOnce(jsonResponse(200, creativeGeneration()));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, websiteDraft()));

    await goToConfirmStep(user);
    await user.click(screen.getByRole("button", { name: "Generate proposal" }));

    await waitFor(() => expect(screen.getByText("Proposal preview")).toBeInTheDocument());

    const draftCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/website-drafts"));
    expect(draftCall).toBeDefined();
    const [, init] = draftCall as [string, RequestInit];
    const body = JSON.parse(init.body as string);

    expect(body.site_config.brand.name).toBe(exampleReformaValenciaConfig.business_profile.name);
    expect(body.site_config.brand.logo?.src).toBe("https://cdn.example.com/real-logo.png");
    expect(JSON.stringify(body.site_config)).toContain("https://cdn.example.com/real-photo.jpg");
  });

  it("Generate proposal never calls publish — the live website is untouched", async () => {
    const user = userEvent.setup();
    renderFlow();
    fetchMock.mockResolvedValueOnce(jsonResponse(200, creativeGeneration()));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, websiteDraft()));

    await goToConfirmStep(user);
    await user.click(screen.getByRole("button", { name: "Generate proposal" }));

    await waitFor(() => expect(screen.getByText("Proposal preview")).toBeInTheDocument());
    expect(screen.getByText(/your live website has not changed/i)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/publish"))).toBe(false);
    expect(onPublished).not.toHaveBeenCalled();
  });

  it("Approve never publishes — Publish remains a separate, explicit action", async () => {
    const user = userEvent.setup();
    renderFlow();
    fetchMock.mockResolvedValueOnce(jsonResponse(200, creativeGeneration()));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, websiteDraft()));

    await goToConfirmStep(user);
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
    fetchMock.mockResolvedValueOnce(jsonResponse(200, creativeGeneration()));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, websiteDraft()));

    await goToConfirmStep(user);
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
    let resolveGeneration: (value: Response) => void = () => {};
    fetchMock.mockImplementationOnce(
      () => new Promise<Response>((resolve) => { resolveGeneration = resolve; }),
    );

    await goToConfirmStep(user);
    const generateButton = screen.getByRole("button", { name: "Generate proposal" });
    await user.click(generateButton);

    expect(screen.getByRole("button", { name: /Generating proposal/ })).toBeDisabled();

    resolveGeneration(jsonResponse(200, creativeGeneration()));
  });

  it("disables Publish while publishing, preventing a duplicate submission", async () => {
    const user = userEvent.setup();
    renderFlow();
    fetchMock.mockResolvedValueOnce(jsonResponse(200, creativeGeneration()));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, websiteDraft()));

    await goToConfirmStep(user);
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
    fetchMock.mockResolvedValueOnce(jsonResponse(200, creativeGeneration({ status: "failed", error: "internal build error" })));

    await goToConfirmStep(user);
    await user.click(screen.getByRole("button", { name: "Generate proposal" }));

    expect(await screen.findByText(/your live website has not changed/i)).toBeInTheDocument();
    // Never a raw backend error code/status leaked into the primary UX.
    expect(screen.queryByText(/500|internal build error|traceback/i)).not.toBeInTheDocument();
  });

  it("a PlatformContract-rejected draft shows only the plain message; the raw violation stays under collapsed Technical details", async () => {
    const user = userEvent.setup();
    renderFlow();
    const buildError =
      'PlatformContract violation(s): An anchor targets "#contact", which has no matching id="contact" anywhere in the build.';
    fetchMock.mockResolvedValueOnce(jsonResponse(200, creativeGeneration()));
    fetchMock.mockResolvedValueOnce(jsonResponse(201, websiteDraft({ status: "build_failed", build_error: buildError })));

    await goToConfirmStep(user, "Create a new design direction");
    await user.click(screen.getByRole("button", { name: "Generate proposal" }));

    const alert = await screen.findByRole("alert");
    const primary = alert.querySelector(":scope > p");
    expect(primary?.textContent).toBe("We couldn't build this proposal. Your live website has not changed.");
    expect(primary?.textContent).not.toMatch(/PlatformContract|id=/);

    // Not deleted — operators can still read it, but only by expanding.
    const detail = screen.getByText(buildError);
    const disclosure = detail.closest("details");
    expect(disclosure).not.toBeNull();
    expect(disclosure?.open).toBe(false);
    expect(disclosure?.querySelector("summary")?.textContent).toBe("Technical details");
    expect(screen.getByRole("button", { name: "Use this design" })).toBeDisabled();
  });

  it("a backend rejection while creating the draft keeps its raw message out of the primary UX", async () => {
    const user = userEvent.setup();
    renderFlow();
    fetchMock.mockResolvedValueOnce(jsonResponse(200, creativeGeneration()));
    fetchMock.mockResolvedValueOnce(
      jsonResponse(422, { error: { code: "validation_error", message: "pages.0.blocks.1.background: invalid" } }),
    );

    await goToConfirmStep(user);
    await user.click(screen.getByRole("button", { name: "Generate proposal" }));

    const alert = await screen.findByRole("alert");
    expect(alert.querySelector(":scope > p")?.textContent).toBe(
      "We couldn't build this proposal. Your live website has not changed.",
    );
    const detail = screen.getByText(/pages\.0\.blocks\.1\.background/);
    expect(detail.closest("details")?.open).toBe(false);
  });
});
