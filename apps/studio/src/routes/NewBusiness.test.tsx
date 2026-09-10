import { generateSiteConfig } from "@generate-web-ai/website-generator";
import { exampleReformaValenciaConfig } from "@generate-web-ai/business-config-types";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TenantOutletContext } from "../layout/AppShell";
import { describeCapability } from "../features/business-preview/workflow";
import { NewBusiness } from "./NewBusiness";

const TENANT_ID = "11111111-1111-1111-1111-111111111111";
const BRIEFING = "Somos una cafeteria de especialidad en la playa de Valencia, abierta desde 2019.";

function renderPage() {
  function StubShell() {
    return <Outlet context={{ tenantId: TENANT_ID } satisfies TenantOutletContext} />;
  }

  return render(
    <MemoryRouter initialEntries={["/businesses/new"]}>
      <Routes>
        <Route element={<StubShell />}>
          <Route path="businesses/new" element={<NewBusiness />} />
          <Route path="businesses/:businessId" element={<NewBusiness />} />
          <Route index element={<p>Dashboard home</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

function renderReopenPage(businessId: string) {
  function StubShell() {
    return <Outlet context={{ tenantId: TENANT_ID } satisfies TenantOutletContext} />;
  }

  return render(
    <MemoryRouter initialEntries={[`/businesses/${businessId}`]}>
      <Routes>
        <Route element={<StubShell />}>
          <Route path="businesses/new" element={<NewBusiness />} />
          <Route path="businesses/:businessId" element={<NewBusiness />} />
          <Route index element={<p>Dashboard home</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

async function analyze(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Describe your business"), BRIEFING);
  await user.click(screen.getByRole("button", { name: "Analyze business" }));
}

function minimalAnalysis(config: unknown) {
  return jsonResponse(200, { proposed_config: config, missing_information: [], questions: [] });
}

// A successful proposal now auto-fetches GET .../automation-recommendation
// (app.routers.businesses) as soon as ProposalReview mounts — every test
// below that reaches "reviewing" with a real proposal needs one of these
// queued right after its analyze response, whether or not the test itself
// cares about the recommendation.
function automationRecommendationResponse(overrides: Partial<Record<string, unknown>> = {}) {
  return jsonResponse(200, {
    lead_notifications: true,
    customer_acknowledgement: true,
    follow_up_enabled: true,
    follow_up_delay_hours: 24,
    ...overrides,
  });
}

const REFORMA_WORKFLOW_PREVIEW = {
  id: "reforma-casa-valencia-lead-capture",
  name: "Reforma Casa Valencia — Lead capture",
  version: 1,
  trigger: { type: "lead.submitted" },
  nodes: [
    { id: "store-lead", type: "action", action: "lead.store", inputs: { action: "lead.store" }, outputs: ["done"] },
    {
      id: "notify-internal",
      type: "action",
      action: "notification.send",
      inputs: { action: "notification.send", template: "lead_internal_notification" },
      outputs: ["done"],
    },
    {
      id: "acknowledge-customer",
      type: "action",
      action: "email.send",
      inputs: { action: "email.send", to: "customer", template: "lead_acknowledgement" },
      outputs: ["done"],
    },
  ],
  connections: [
    { source: "trigger", source_output: "done", target: "store-lead" },
    { source: "store-lead", source_output: "done", target: "notify-internal" },
    { source: "store-lead", source_output: "done", target: "acknowledge-customer" },
  ],
  error_handling: { strategy: "stop", max_retries: 0, notify_on_failure: false },
  required_capabilities: ["email.send", "lead.store", "notification.send"],
};

// Same shape as REFORMA_WORKFLOW_PREVIEW, but with automation.follow_up
// enabled — the real backend's generate_lead_capture_workflow output
// once notify-internal is followed by wait -> lookup -> condition ->
// follow-up notification (apps/api's app.domain.workflow_config.generator).
const REFORMA_WORKFLOW_PREVIEW_WITH_FOLLOW_UP = {
  ...REFORMA_WORKFLOW_PREVIEW,
  nodes: [
    ...REFORMA_WORKFLOW_PREVIEW.nodes.slice(0, 2),
    { id: "wait-follow-up", type: "action", action: "wait", inputs: { action: "wait", hours: 48 }, outputs: ["done"] },
    {
      id: "lookup-lead",
      type: "action",
      action: "lead.lookup",
      inputs: { action: "lead.lookup" },
      outputs: ["done"],
    },
    {
      id: "check-lead-status",
      type: "condition",
      condition: { field: "lead.status", operator: "equals", value: "new" },
      outputs: ["true", "false"],
    },
    {
      id: "notify-follow-up",
      type: "action",
      action: "notification.send",
      inputs: { action: "notification.send", template: "lead_follow_up" },
      outputs: ["done"],
    },
    ...REFORMA_WORKFLOW_PREVIEW.nodes.slice(2),
  ],
  connections: [
    ...REFORMA_WORKFLOW_PREVIEW.connections.slice(0, 2),
    { source: "notify-internal", source_output: "done", target: "wait-follow-up" },
    { source: "wait-follow-up", source_output: "done", target: "lookup-lead" },
    { source: "lookup-lead", source_output: "done", target: "check-lead-status" },
    { source: "check-lead-status", source_output: "true", target: "notify-follow-up" },
    ...REFORMA_WORKFLOW_PREVIEW.connections.slice(2),
  ],
  required_capabilities: ["email.send", "lead.lookup", "lead.store", "notification.send", "wait"],
};

describe("NewBusiness onboarding flow", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("analysis success: shows the editable proposal after a successful analyze call", async () => {
    fetchMock.mockResolvedValueOnce(
      minimalAnalysis({
        schema_version: 1,
        business_profile: { name: "Cafe del Mar", slug: "cafe-del-mar", industry: "restaurant" },
        lead_management: {},
        automation: {},
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await analyze(user);

    expect(await screen.findByDisplayValue("Cafe del Mar")).toBeInTheDocument();
    expect(screen.getByDisplayValue("cafe-del-mar")).toBeInTheDocument();

    const [, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = requestInit.headers as Record<string, string>;
    expect(headers["X-Tenant-Id"]).toBe(TENANT_ID);
  });

  it("missing information displayed: surfaces missing_information and questions from the analysis", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, {
        proposed_config: null,
        missing_information: ["business_profile.name (business name)"],
        questions: ["What is the legal or trading name of the business?"],
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await analyze(user);

    expect(await screen.findByText("business_profile.name (business name)")).toBeInTheDocument();
    expect(screen.getByText("What is the legal or trading name of the business?")).toBeInTheDocument();
    expect(screen.getByText(/couldn't propose a full configuration/i)).toBeInTheDocument();
  });

  it("proposal editable: editing a field changes what gets sent to POST /businesses", async () => {
    fetchMock.mockResolvedValueOnce(
      minimalAnalysis({
        schema_version: 1,
        business_profile: { name: "Cafe del Mar", slug: "cafe-del-mar", industry: "restaurant" },
        lead_management: {},
        automation: {},
      }),
    );
    fetchMock.mockResolvedValueOnce(automationRecommendationResponse());
    fetchMock.mockResolvedValueOnce(
      jsonResponse(201, { id: "biz-1", name: "Cafe del Sol", slug: "cafe-del-sol", status: "draft", raw_description: BRIEFING }),
    );
    fetchMock.mockResolvedValueOnce(jsonResponse(200, null)); // workflow-preview: no automation on this bare config
    fetchMock.mockResolvedValueOnce(jsonResponse(200, null)); // automation state: never activated
    fetchMock.mockResolvedValueOnce(jsonResponse(200, null)); // website state: never published
    fetchMock.mockResolvedValueOnce(jsonResponse(200, [])); // leads: none captured yet
    fetchMock.mockResolvedValueOnce(jsonResponse(200, null)); // custom domain: never attached
    fetchMock.mockResolvedValueOnce(jsonResponse(200, [])); // website versions: none yet
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { checks: [], has_blocking_issues: false })); // production readiness
    const user = userEvent.setup();
    renderPage();

    await analyze(user);
    const nameInput = await screen.findByDisplayValue("Cafe del Mar");
    await user.clear(nameInput);
    await user.type(nameInput, "Cafe del Sol");
    const slugInput = screen.getByDisplayValue("cafe-del-mar");
    await user.clear(slugInput);
    await user.type(slugInput, "cafe-del-sol");

    await user.click(screen.getByRole("button", { name: "Create business" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(10));
    const [, createInit] = fetchMock.mock.calls[2] as [string, RequestInit];
    const body = JSON.parse(createInit.body as string) as { name: string; slug: string };
    expect(body.name).toBe("Cafe del Sol");
    expect(body.slug).toBe("cafe-del-sol");
  });

  it("follow-up controls: enabling follow-up and setting the delay sends automation.follow_up.delay_hours on save", async () => {
    fetchMock.mockResolvedValueOnce(
      minimalAnalysis({
        schema_version: 1,
        business_profile: { name: "Cafe del Mar", slug: "cafe-del-mar", industry: "restaurant" },
        lead_management: {},
        automation: {},
      }),
    );
    fetchMock.mockResolvedValueOnce(automationRecommendationResponse());
    fetchMock.mockResolvedValueOnce(
      jsonResponse(201, { id: "biz-1", name: "Cafe del Mar", slug: "cafe-del-mar", status: "draft", raw_description: BRIEFING }),
    );
    fetchMock.mockResolvedValueOnce(jsonResponse(200, null)); // workflow-preview
    fetchMock.mockResolvedValueOnce(jsonResponse(200, null)); // automation state
    fetchMock.mockResolvedValueOnce(jsonResponse(200, null)); // website state
    fetchMock.mockResolvedValueOnce(jsonResponse(200, [])); // leads
    fetchMock.mockResolvedValueOnce(jsonResponse(200, null)); // custom domain
    fetchMock.mockResolvedValueOnce(jsonResponse(200, [])); // website versions
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { checks: [], has_blocking_issues: false })); // production readiness
    const user = userEvent.setup();
    renderPage();

    await analyze(user);
    await screen.findByDisplayValue("Cafe del Mar");

    // Off by default with no proposed automation — the delay input
    // starts disabled.
    const delayInput = screen.getByLabelText("Follow-up delay (hours)");
    expect(delayInput).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: "Follow up automatically" }));
    expect(delayInput).toBeEnabled();
    await user.clear(delayInput);
    await user.type(delayInput, "72");

    await user.click(screen.getByRole("button", { name: "Create business" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(10));
    const [, createInit] = fetchMock.mock.calls[2] as [string, RequestInit];
    const body = JSON.parse(createInit.body as string) as {
      config: { automation: { follow_up: { enabled: boolean; delay_hours: number } } };
    };
    expect(body.config.automation.follow_up).toEqual({ enabled: true, delay_hours: 72 });
  });

  it("follow-up controls: an out-of-range delay blocks save with a clear error, never calling POST /businesses", async () => {
    fetchMock.mockResolvedValueOnce(
      minimalAnalysis({
        schema_version: 1,
        business_profile: { name: "Cafe del Mar", slug: "cafe-del-mar", industry: "restaurant" },
        lead_management: {},
        automation: {},
      }),
    );
    fetchMock.mockResolvedValueOnce(automationRecommendationResponse());
    const user = userEvent.setup();
    renderPage();

    await analyze(user);
    await screen.findByDisplayValue("Cafe del Mar");

    await user.click(screen.getByRole("checkbox", { name: "Follow up automatically" }));
    const delayInput = screen.getByLabelText("Follow-up delay (hours)");
    await user.clear(delayInput);
    await user.type(delayInput, "1000");

    await user.click(screen.getByRole("button", { name: "Create business" }));

    expect(await screen.findByText(/Follow-up delay must be a whole number of hours between 1 and 720/)).toBeInTheDocument();
    // Only the earlier /analyze call and the auto-fetched recommendation
    // — never a POST to /businesses.
    expect(fetchMock).toHaveBeenCalledTimes(2);
    // /businesses/analyze is a POST too — what must never happen is a
    // POST to the *create* endpoint, plain "/businesses".
    expect(
      fetchMock.mock.calls.every(
        ([url, init]) => !((url as string).endsWith("/businesses") && (init as RequestInit | undefined)?.method === "POST"),
      ),
    ).toBe(true);
  });

  it("automation recommendation: shown automatically after a successful analysis, for the detected vertical", async () => {
    fetchMock.mockResolvedValueOnce(
      minimalAnalysis({
        schema_version: 1,
        business_profile: { name: "Cafe del Mar", slug: "cafe-del-mar", industry: "restaurant" },
        lead_management: {},
        automation: {},
      }),
    );
    fetchMock.mockResolvedValueOnce(
      automationRecommendationResponse({ follow_up_enabled: false, follow_up_delay_hours: 24 }),
    );
    const user = userEvent.setup();
    renderPage();

    await analyze(user);
    await screen.findByDisplayValue("Cafe del Mar");

    // Auto-fetched — no click needed just to see it.
    expect(await screen.findByText("Recommended for restaurant")).toBeInTheDocument();
    expect(screen.getByText("Internal notification · Customer acknowledgement")).toBeInTheDocument();
    const recommendationCall = fetchMock.mock.calls.find(([url]) => (url as string).includes("automation-recommendation"));
    expect(recommendationCall).toBeDefined();
    const [recommendationUrl] = recommendationCall as [string, RequestInit];
    expect(recommendationUrl).toContain("vertical=restaurant");
  });

  it("automation recommendation: never modifies the checkboxes on its own — only Apply does, on an explicit click", async () => {
    fetchMock.mockResolvedValueOnce(
      minimalAnalysis({
        schema_version: 1,
        business_profile: { name: "Cafe del Mar", slug: "cafe-del-mar", industry: "restaurant" },
        lead_management: {},
        automation: {},
      }),
    );
    fetchMock.mockResolvedValueOnce(automationRecommendationResponse());
    const user = userEvent.setup();
    renderPage();
    await analyze(user);
    await screen.findByDisplayValue("Cafe del Mar");

    // Visible automatically, but the checkboxes haven't moved.
    await screen.findByText("Recommended for restaurant");
    expect(screen.getByRole("checkbox", { name: "Notify the team of new leads" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Send the customer an acknowledgement" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Follow up automatically" })).not.toBeChecked();

    await user.click(screen.getByRole("button", { name: "Apply recommended automation" }));

    expect(screen.getByRole("checkbox", { name: "Notify the team of new leads" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Send the customer an acknowledgement" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Follow up automatically" })).toBeChecked();
    expect(screen.getByLabelText("Follow-up delay (hours)")).toHaveValue(24);
    // Still user-editable afterward — nothing about Apply locks the field.
    await user.click(screen.getByRole("checkbox", { name: "Follow up automatically" }));
    expect(screen.getByRole("checkbox", { name: "Follow up automatically" })).not.toBeChecked();
  });

  it("automation recommendation: works the same for a vertical with no dedicated template (generic fallback)", async () => {
    fetchMock.mockResolvedValueOnce(
      minimalAnalysis({
        schema_version: 1,
        business_profile: { name: "Hotel Mar Azul", slug: "hotel-mar-azul", industry: "hotel" },
        lead_management: {},
        automation: {},
      }),
    );
    fetchMock.mockResolvedValueOnce(
      automationRecommendationResponse({ customer_acknowledgement: false, follow_up_enabled: false }),
    );
    const user = userEvent.setup();
    renderPage();
    await analyze(user);
    await screen.findByDisplayValue("Hotel Mar Azul");

    expect(await screen.findByText("Recommended for hotel")).toBeInTheDocument();
    expect(screen.getByText("Internal notification")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Apply recommended automation" }));

    expect(screen.getByRole("checkbox", { name: "Notify the team of new leads" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Send the customer an acknowledgement" })).not.toBeChecked();
  });

  it("create business: POST /businesses is called once, with the tenant header, and success is shown", async () => {
    fetchMock.mockResolvedValueOnce(
      minimalAnalysis({
        schema_version: 1,
        business_profile: { name: "Cafe del Mar", slug: "cafe-del-mar", industry: "restaurant" },
        lead_management: {},
        automation: {},
      }),
    );
    fetchMock.mockResolvedValueOnce(automationRecommendationResponse());
    fetchMock.mockResolvedValueOnce(
      jsonResponse(201, { id: "biz-1", name: "Cafe del Mar", slug: "cafe-del-mar", status: "draft", raw_description: BRIEFING }),
    );
    fetchMock.mockResolvedValueOnce(jsonResponse(200, null));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, null)); // automation state: never activated
    fetchMock.mockResolvedValueOnce(jsonResponse(200, null)); // website state: never published
    fetchMock.mockResolvedValueOnce(jsonResponse(200, [])); // leads: none captured yet
    fetchMock.mockResolvedValueOnce(jsonResponse(200, null)); // custom domain: never attached
    fetchMock.mockResolvedValueOnce(jsonResponse(200, [])); // website versions: none yet
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { checks: [], has_blocking_issues: false })); // production readiness
    const user = userEvent.setup();
    renderPage();

    await analyze(user);
    await user.click(await screen.findByRole("button", { name: "Create business" }));

    expect(await screen.findByText(/Business "Cafe del Mar" created/)).toBeInTheDocument();

    const [createUrl, createInit] = fetchMock.mock.calls[2] as [string, RequestInit];
    expect(createUrl).toContain("/businesses");
    expect(createUrl).not.toContain("/analyze");
    const headers = createInit.headers as Record<string, string>;
    expect(headers["X-Tenant-Id"]).toBe(TENANT_ID);
  });

  it("analyzer unavailable: a 503 from /businesses/analyze shows a human 'AI unavailable' message, not raw JSON", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(503, {
        error: { code: "business_analyzer_not_configured", message: "The AI Business Analyzer is not configured on this server." },
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await analyze(user);

    expect(await screen.findByText("AI analyzer unavailable")).toBeInTheDocument();
    // The raw error code may exist for developers, but only tucked away
    // behind a collapsed <details> — never as visible primary content.
    expect(screen.getByText(/business_analyzer_not_configured/)).not.toBeVisible();
  });

  it("business is not persisted before approval: analyzing (and the auto-fetched recommendation) never calls POST /businesses", async () => {
    fetchMock.mockResolvedValueOnce(
      minimalAnalysis({
        schema_version: 1,
        business_profile: { name: "Cafe del Mar", slug: "cafe-del-mar", industry: "restaurant" },
        lead_management: {},
        automation: {},
      }),
    );
    fetchMock.mockResolvedValueOnce(automationRecommendationResponse());
    const user = userEvent.setup();
    renderPage();

    await analyze(user);
    await screen.findByDisplayValue("Cafe del Mar");
    await screen.findByText("Recommended for restaurant");

    // Only the read-only /analyze and .../automation-recommendation
    // calls — neither is a POST, so nothing was persisted.
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [analyzeUrl] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(analyzeUrl).toContain("/businesses/analyze");
    // /businesses/analyze is a POST too — what must never happen is a
    // POST to the *create* endpoint, plain "/businesses".
    expect(
      fetchMock.mock.calls.every(
        ([url, init]) => !((url as string).endsWith("/businesses") && (init as RequestInit | undefined)?.method === "POST"),
      ),
    ).toBe(true);
  });
});

describe("NewBusiness preview step", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  async function createReformaBusiness(
    user: ReturnType<typeof userEvent.setup>,
    workflowPreviewBody: unknown,
    automationStateBody: unknown = null,
    websiteStateBody: unknown = null,
    leadsBody: unknown = [],
    customDomainBody: unknown = null,
    websiteVersionsBody: unknown = [],
    productionReadinessBody: unknown = { checks: [], has_blocking_issues: false },
  ) {
    fetchMock.mockResolvedValueOnce(minimalAnalysis(exampleReformaValenciaConfig));
    fetchMock.mockResolvedValueOnce(automationRecommendationResponse()); // auto-fetched once ProposalReview mounts
    fetchMock.mockResolvedValueOnce(
      jsonResponse(201, {
        id: "biz-reforma",
        name: exampleReformaValenciaConfig.business_profile.name,
        slug: exampleReformaValenciaConfig.business_profile.slug,
        status: "draft",
        raw_description: BRIEFING,
        config: exampleReformaValenciaConfig,
      }),
    );
    fetchMock.mockResolvedValueOnce(jsonResponse(200, workflowPreviewBody));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, automationStateBody)); // automation state, defaults to "never activated"
    fetchMock.mockResolvedValueOnce(jsonResponse(200, websiteStateBody)); // website state, defaults to "never published"
    fetchMock.mockResolvedValueOnce(jsonResponse(200, leadsBody)); // leads, defaults to "none captured yet"
    fetchMock.mockResolvedValueOnce(jsonResponse(200, customDomainBody)); // custom domain, defaults to "never attached"
    fetchMock.mockResolvedValueOnce(jsonResponse(200, websiteVersionsBody)); // website versions, defaults to "none yet"
    fetchMock.mockResolvedValueOnce(jsonResponse(200, productionReadinessBody)); // production readiness

    renderPage();
    await analyze(user);
    await user.click(await screen.findByRole("button", { name: "Create business" }));
    await screen.findByText(/Business ".*" created/);
  }

  it("approved BusinessConfig → website preview: renders hero/services/CTA/contact/branding from the real generated SiteConfig", async () => {
    const user = userEvent.setup();
    await createReformaBusiness(user, REFORMA_WORKFLOW_PREVIEW);

    // The expectations themselves come from calling the real generator —
    // proving the preview reflects generateSiteConfig's actual output,
    // not a hand-written approximation of it.
    const expectedSite = generateSiteConfig(exampleReformaValenciaConfig);
    const page = expectedSite.pages[0];
    const hero = page?.blocks.find((b) => b.type === "hero");
    const services = page?.blocks.find((b) => b.type === "services");
    const cta = page?.blocks.find((b) => b.type === "cta");
    const contact = page?.blocks.find((b) => b.type === "contact");
    if (hero?.type !== "hero" || services?.type !== "services" || cta?.type !== "cta" || contact?.type !== "contact") {
      throw new Error("fixture-derived SiteConfig is missing an expected block");
    }

    expect(await screen.findByRole("heading", { name: hero.content.heading })).toBeInTheDocument();
    for (const item of services.content.items) {
      expect(screen.getByText(item.title)).toBeInTheDocument();
    }
    expect(screen.getByRole("heading", { name: cta.content.heading })).toBeInTheDocument();
    for (const detail of contact.content.details ?? []) {
      expect(screen.getByText((_, node) => node?.textContent === `${detail.label}: ${detail.value}`)).toBeInTheDocument();
    }
    // Scoped: the hero heading is the same business name, so an
    // unscoped query would match both.
    expect(document.querySelector(".site-preview__brand-name")).toHaveTextContent(expectedSite.brand.name);
    if (expectedSite.brand.tagline) {
      expect(document.querySelector(".site-preview__tagline")).toHaveTextContent(expectedSite.brand.tagline);
    }
    expect(document.querySelectorAll(".site-preview__swatch")).toHaveLength(5);
  });

  it("publish requires explicit confirmation before calling the API", async () => {
    const user = userEvent.setup();
    await createReformaBusiness(user, REFORMA_WORKFLOW_PREVIEW);
    const callsBeforePublishing = fetchMock.mock.calls.length;

    await user.click(await screen.findByRole("button", { name: "Publish website" }));

    // Just clicking "Publish website" only opens the confirmation — it
    // must not have called the API yet.
    expect(fetchMock).toHaveBeenCalledTimes(callsBeforePublishing);
    expect(screen.getByText("Confirm publication")).toBeInTheDocument();
    expect(screen.getByText(/publicly reachable/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(fetchMock).toHaveBeenCalledTimes(callsBeforePublishing);
    expect(screen.queryByText("Confirm publication")).not.toBeInTheDocument();
  });

  it("publish success shows the Published state with a real Open live website link", async () => {
    const user = userEvent.setup();
    await createReformaBusiness(user, REFORMA_WORKFLOW_PREVIEW);
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, {
        status: "live",
        live_url: "https://site-biz-reforma.my-team.workers.dev/",
        deployment_id: "site-biz-reforma",
        deployed_at: "2026-08-27T00:00:00Z",
        updated_at: "2026-08-27T00:00:00Z",
      }),
    );

    await user.click(await screen.findByRole("button", { name: "Publish website" }));
    await user.click(screen.getByRole("button", { name: "Confirm publish" }));

    expect(await screen.findByText(/Published/)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Open live website" });
    expect(link).toHaveAttribute("href", "https://site-biz-reforma.my-team.workers.dev/");

    const publishCall = fetchMock.mock.calls.find(([url]) => (url as string).includes("/website/publish"));
    expect(publishCall).toBeDefined();
    const [, publishInit] = publishCall as [string, RequestInit];
    expect(publishInit.method).toBe("POST");
    const sentSiteConfig = JSON.parse(publishInit.body as string) as { brand: { name: string } };
    expect(sentSiteConfig.brand.name).toBe(generateSiteConfig(exampleReformaValenciaConfig).brand.name);
  });

  it("publish failure shows a human error, never Published, and offers a retry", async () => {
    const user = userEvent.setup();
    await createReformaBusiness(user, REFORMA_WORKFLOW_PREVIEW);
    fetchMock.mockResolvedValueOnce(
      jsonResponse(503, {
        error: { code: "website_publisher_not_configured", message: "Website publishing is not configured on this server." },
      }),
    );

    await user.click(await screen.findByRole("button", { name: "Publish website" }));
    await user.click(screen.getByRole("button", { name: "Confirm publish" }));

    expect(await screen.findByText("Publishing isn't set up on this server")).toBeInTheDocument();
    expect(screen.queryByText(/^Published/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open live website" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("reload of the preview step shows the persisted Published state without re-publishing", async () => {
    const user = userEvent.setup();
    await createReformaBusiness(user, REFORMA_WORKFLOW_PREVIEW, null, {
      status: "live",
      live_url: "https://site-biz-reforma.my-team.workers.dev/",
      deployment_id: "site-biz-reforma",
      deployed_at: "2026-08-27T00:00:00Z",
      updated_at: "2026-08-27T00:00:00Z",
    });

    // Backend truth is already "live" as soon as the step opens —
    // nothing here ever called .../website/publish.
    expect(await screen.findByText(/Published/)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Open live website" });
    expect(link).toHaveAttribute("href", "https://site-biz-reforma.my-team.workers.dev/");
    const publishCall = fetchMock.mock.calls.find(([url]) => (url as string).includes("/website/publish"));
    expect(publishCall).toBeUndefined();
  });

  it("approved BusinessConfig → workflow preview: shows the real workflow's diagram, trigger, actions, and required capabilities", async () => {
    const user = userEvent.setup();
    await createReformaBusiness(user, REFORMA_WORKFLOW_PREVIEW);

    // "Lead submitted" appears twice on purpose: once as the diagram's
    // trigger box, once as the "Trigger" fact's value.
    expect(await screen.findAllByText("Lead submitted")).toHaveLength(2);
    expect(screen.getByText("Store lead")).toBeInTheDocument();
    expect(screen.getByText("Notify")).toBeInTheDocument();
    expect(screen.getByText("Customer email")).toBeInTheDocument();

    expect(screen.getByText("Workflow name")).toBeInTheDocument();
    expect(screen.getByText(REFORMA_WORKFLOW_PREVIEW.name)).toBeInTheDocument();
    for (const capability of REFORMA_WORKFLOW_PREVIEW.required_capabilities) {
      expect(screen.getByText(describeCapability(capability))).toBeInTheDocument();
    }
  });

  it("automation preview with follow-up enabled shows the wait -> lookup -> condition -> follow-up chain and the configured delay", async () => {
    const user = userEvent.setup();
    await createReformaBusiness(user, REFORMA_WORKFLOW_PREVIEW_WITH_FOLLOW_UP);

    // Every real node in the chain, distinctly labeled — including
    // telling the two notification.send nodes apart.
    expect(await screen.findByText("Store lead")).toBeInTheDocument();
    expect(screen.getByText("Notify")).toBeInTheDocument();
    expect(screen.getByText("Wait 48h")).toBeInTheDocument();
    expect(screen.getByText("Check lead status")).toBeInTheDocument();
    expect(screen.getByText("Follow-up notification")).toBeInTheDocument();

    // The explicit "Follow-up" fact states enabled/disabled and the
    // configured delay in one place, not just implied by the diagram.
    expect(screen.getByText("Follow-up")).toBeInTheDocument();
    expect(screen.getByText(/Enabled — waits 48h/)).toBeInTheDocument();

    for (const capability of REFORMA_WORKFLOW_PREVIEW_WITH_FOLLOW_UP.required_capabilities) {
      expect(screen.getByText(describeCapability(capability))).toBeInTheDocument();
    }
  });

  it("automation preview without follow-up shows it as disabled", async () => {
    const user = userEvent.setup();
    await createReformaBusiness(user, REFORMA_WORKFLOW_PREVIEW);

    expect(await screen.findByText("Follow-up")).toBeInTheDocument();
    expect(screen.getByText("Disabled")).toBeInTheDocument();
  });

  it("business without automation shows appropriate empty state", async () => {
    const user = userEvent.setup();
    await createReformaBusiness(user, null);

    expect(await screen.findByText(/No automation is configured for this business yet/)).toBeInTheDocument();
    expect(screen.queryByText("Workflow name")).not.toBeInTheDocument();
  });

  it("activation requires explicit confirmation before calling the API", async () => {
    const user = userEvent.setup();
    await createReformaBusiness(user, REFORMA_WORKFLOW_PREVIEW);
    const callsBeforeActivating = fetchMock.mock.calls.length;

    await user.click(await screen.findByRole("button", { name: "Activate automation" }));

    // Just clicking "Activate automation" only opens the confirmation —
    // it must not have called the API yet.
    expect(fetchMock).toHaveBeenCalledTimes(callsBeforeActivating);
    expect(screen.getByText("Confirm activation")).toBeInTheDocument();
    expect(screen.getByText(/start executing real actions/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(fetchMock).toHaveBeenCalledTimes(callsBeforeActivating);
    expect(screen.queryByText("Confirm activation")).not.toBeInTheDocument();
  });

  it("activation success shows the Active state", async () => {
    const user = userEvent.setup();
    await createReformaBusiness(user, REFORMA_WORKFLOW_PREVIEW);
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, {
        workflow_id: "reforma-casa-valencia-lead-capture",
        remote_id: "42",
        name: REFORMA_WORKFLOW_PREVIEW.name,
        status: "active",
        active: true,
        version: 1,
        required_capabilities: REFORMA_WORKFLOW_PREVIEW.required_capabilities,
        activated_at: "2026-08-27T00:00:00Z",
        updated_at: "2026-08-27T00:00:00Z",
      }),
    );

    await user.click(await screen.findByRole("button", { name: "Activate automation" }));
    await user.click(screen.getByRole("button", { name: "Confirm activate" }));

    expect(await screen.findByText(/Active/)).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Deactivate" })).toBeInTheDocument();

    const activateCall = fetchMock.mock.calls.find(([url]) => (url as string).includes("/automation/activate"));
    expect(activateCall).toBeDefined();
    const [, activateInit] = activateCall as [string, RequestInit];
    expect(activateInit.method).toBe("POST");
  });

  it("deactivation success shows the Inactive state and offers Activate again", async () => {
    const user = userEvent.setup();
    await createReformaBusiness(user, REFORMA_WORKFLOW_PREVIEW, {
      workflow_id: "reforma-casa-valencia-lead-capture",
      remote_id: "42",
      name: REFORMA_WORKFLOW_PREVIEW.name,
      status: "active",
      active: true,
      version: 1,
      required_capabilities: REFORMA_WORKFLOW_PREVIEW.required_capabilities,
      activated_at: "2026-08-27T00:00:00Z",
      updated_at: "2026-08-27T00:00:00Z",
    });

    expect(await screen.findByRole("button", { name: "Deactivate" })).toBeInTheDocument();

    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, {
        workflow_id: "reforma-casa-valencia-lead-capture",
        remote_id: "42",
        name: REFORMA_WORKFLOW_PREVIEW.name,
        status: "inactive",
        active: false,
        version: 1,
        required_capabilities: REFORMA_WORKFLOW_PREVIEW.required_capabilities,
        activated_at: "2026-08-27T00:00:00Z",
        updated_at: "2026-08-27T00:01:00Z",
      }),
    );

    await user.click(screen.getByRole("button", { name: "Deactivate" }));

    expect(await screen.findByRole("button", { name: "Activate automation" })).toBeInTheDocument();
    expect(screen.queryByText(/^Active/)).not.toBeInTheDocument();

    const deactivateCall = fetchMock.mock.calls.find(([url]) => (url as string).includes("/automation/deactivate"));
    expect(deactivateCall).toBeDefined();
    const [, deactivateInit] = deactivateCall as [string, RequestInit];
    expect(deactivateInit.method).toBe("POST");
  });

  it("reload of the preview step shows the persisted Active state without re-activating", async () => {
    const user = userEvent.setup();
    await createReformaBusiness(user, REFORMA_WORKFLOW_PREVIEW, {
      workflow_id: "reforma-casa-valencia-lead-capture",
      remote_id: "42",
      name: REFORMA_WORKFLOW_PREVIEW.name,
      status: "active",
      active: true,
      version: 1,
      required_capabilities: REFORMA_WORKFLOW_PREVIEW.required_capabilities,
      activated_at: "2026-08-27T00:00:00Z",
      updated_at: "2026-08-27T00:00:00Z",
    });

    // Backend truth is already "active" as soon as the step opens —
    // nothing here ever called .../automation/activate.
    expect(await screen.findByText(/Active/)).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    const activateCall = fetchMock.mock.calls.find(([url]) => (url as string).includes("/automation/activate"));
    expect(activateCall).toBeUndefined();
  });

  it("activation failure (missing n8n config) shows a human error, never Active", async () => {
    const user = userEvent.setup();
    await createReformaBusiness(user, REFORMA_WORKFLOW_PREVIEW);
    fetchMock.mockResolvedValueOnce(
      jsonResponse(503, { error: { code: "n8n_not_configured", message: "n8n is not configured on this server." } }),
    );

    await user.click(await screen.findByRole("button", { name: "Activate automation" }));
    await user.click(screen.getByRole("button", { name: "Confirm activate" }));

    expect(await screen.findByText("Automation isn't set up on this server")).toBeInTheDocument();
    expect(screen.queryByText(/^Active/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("generated content comes from the real configs, not a fabricated preview", async () => {
    const config = {
      schema_version: 1,
      business_profile: {
        name: "Zzz Unique Business Name",
        slug: "zzz-unique-business-name",
        industry: "other",
        description: "Zzz unique description text nobody else would produce by accident.",
        services: [{ id: "zzz-service", name: "Zzz Unique Service", description: "Zzz unique service description." }],
      },
      lead_management: {},
      automation: {},
    };
    fetchMock.mockResolvedValueOnce(minimalAnalysis(config));
    fetchMock.mockResolvedValueOnce(automationRecommendationResponse());
    fetchMock.mockResolvedValueOnce(
      jsonResponse(201, {
        id: "biz-zzz",
        name: "Zzz Unique Business Name",
        slug: "zzz-unique-business-name",
        status: "draft",
        raw_description: BRIEFING,
        config,
      }),
    );
    fetchMock.mockResolvedValueOnce(jsonResponse(200, null));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, null)); // automation state: never activated
    fetchMock.mockResolvedValueOnce(jsonResponse(200, null)); // website state: never published
    fetchMock.mockResolvedValueOnce(jsonResponse(200, [])); // leads: none captured yet
    fetchMock.mockResolvedValueOnce(jsonResponse(200, null)); // custom domain: never attached
    fetchMock.mockResolvedValueOnce(jsonResponse(200, [])); // website versions: none yet
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { checks: [], has_blocking_issues: false })); // production readiness
    const user = userEvent.setup();
    renderPage();

    await analyze(user);
    await user.click(await screen.findByRole("button", { name: "Create business" }));

    expect(await screen.findByRole("heading", { name: "Zzz Unique Business Name" })).toBeInTheDocument();
    expect(screen.getByText("Zzz unique description text nobody else would produce by accident.")).toBeInTheDocument();
    expect(screen.getByText("Zzz Unique Service")).toBeInTheDocument();
  });

  it("Edit business goes back to the proposal and Save changes calls PUT /businesses/{id}", async () => {
    const user = userEvent.setup();
    await createReformaBusiness(user, REFORMA_WORKFLOW_PREVIEW);

    await user.click(screen.getByRole("button", { name: "Edit business" }));
    expect(await screen.findByDisplayValue(exampleReformaValenciaConfig.business_profile.name)).toBeInTheDocument();

    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, {
        id: "biz-reforma",
        name: exampleReformaValenciaConfig.business_profile.name,
        slug: exampleReformaValenciaConfig.business_profile.slug,
        status: "draft",
        raw_description: BRIEFING,
        config: exampleReformaValenciaConfig,
      }),
    );
    fetchMock.mockResolvedValueOnce(jsonResponse(200, REFORMA_WORKFLOW_PREVIEW));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, null)); // automation state: never activated
    fetchMock.mockResolvedValueOnce(jsonResponse(200, null)); // website state: never published
    fetchMock.mockResolvedValueOnce(jsonResponse(200, [])); // leads: none captured yet
    fetchMock.mockResolvedValueOnce(jsonResponse(200, null)); // custom domain: never attached
    fetchMock.mockResolvedValueOnce(jsonResponse(200, [])); // website versions: none yet
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { checks: [], has_blocking_issues: false })); // production readiness

    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await screen.findByText(/created/);

    const putCall = fetchMock.mock.calls.find(([, init]) => (init as RequestInit).method === "PUT");
    expect(putCall).toBeDefined();
    const [putUrl] = putCall as [string, RequestInit];
    expect(putUrl).toContain("/businesses/biz-reforma");
  });

  it("editing an existing business shows its persisted automation and never auto-applies a recommendation over it", async () => {
    const user = userEvent.setup();
    await createReformaBusiness(user, REFORMA_WORKFLOW_PREVIEW);
    // createReformaBusiness's own auto-fetch (for the fresh proposal) has
    // already happened by this point — count calls from here on, so this
    // assertion is only about what "Edit business" itself triggers.
    const callsBeforeEdit = fetchMock.mock.calls.length;

    await user.click(screen.getByRole("button", { name: "Edit business" }));
    await screen.findByDisplayValue(exampleReformaValenciaConfig.business_profile.name);

    // Exactly the persisted fixture's automation.follow_up (enabled,
    // delay_hours: 48) — never overwritten just by opening this screen.
    expect(screen.getByRole("checkbox", { name: "Notify the team of new leads" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Send the customer an acknowledgement" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Follow up automatically" })).toBeChecked();
    expect(screen.getByLabelText("Follow-up delay (hours)")).toHaveValue(48);

    const recommendationCall = fetchMock.mock.calls
      .slice(callsBeforeEdit)
      .find(([url]) => (url as string).includes("automation-recommendation"));
    expect(recommendationCall).toBeUndefined();
  });

  it("editing an existing business: clicking 'Show recommended automation' still lets the user apply it explicitly", async () => {
    const user = userEvent.setup();
    await createReformaBusiness(user, REFORMA_WORKFLOW_PREVIEW);
    // createReformaBusiness's own auto-fetch (for the fresh proposal) has
    // already happened by this point — count calls from here on, so this
    // assertion is only about what "Edit business" itself triggers.
    const callsBeforeEdit = fetchMock.mock.calls.length;

    await user.click(screen.getByRole("button", { name: "Edit business" }));
    await screen.findByDisplayValue(exampleReformaValenciaConfig.business_profile.name);

    // Nothing fetched yet, and the persisted values (follow-up delay 48h)
    // are still showing — matching the sibling test above.
    expect(screen.getByLabelText("Follow-up delay (hours)")).toHaveValue(48);
    expect(
      fetchMock.mock.calls.slice(callsBeforeEdit).some(([url]) => (url as string).includes("automation-recommendation")),
    ).toBe(false);

    fetchMock.mockResolvedValueOnce(
      automationRecommendationResponse({ follow_up_enabled: true, follow_up_delay_hours: 24 }),
    );
    await user.click(screen.getByRole("button", { name: "Show recommended automation" }));

    // exampleReformaValenciaConfig's industry is "home_renovation".
    await screen.findByText("Recommended for home renovation");
    expect(screen.getByText("Internal notification · Customer acknowledgement · Follow-up after 24h")).toBeInTheDocument();

    // Still just a suggestion — the persisted 48h value is untouched
    // until the user explicitly applies it.
    expect(screen.getByLabelText("Follow-up delay (hours)")).toHaveValue(48);

    await user.click(screen.getByRole("button", { name: "Apply recommended automation" }));
    expect(screen.getByLabelText("Follow-up delay (hours)")).toHaveValue(24);
  });

  it("leads: shows an empty state when none have been captured yet", async () => {
    const user = userEvent.setup();
    await createReformaBusiness(user, REFORMA_WORKFLOW_PREVIEW, null, null, []);

    expect(await screen.findByText("No leads captured yet for this business.")).toBeInTheDocument();
  });

  it("leads: renders name, email, phone, message, and date for each captured lead", async () => {
    const user = userEvent.setup();
    await createReformaBusiness(user, REFORMA_WORKFLOW_PREVIEW, null, null, [
      {
        id: "lead-1",
        business_id: "biz-reforma",
        source: "website_form",
        name: "Juan Perez",
        email: "juan@example.com",
        phone: "+34600000000",
        message: "Quiero un presupuesto para mi cocina.",
        status: "new",
        created_at: "2026-08-28T10:00:00Z",
      },
    ]);

    expect(await screen.findByText("Juan Perez")).toBeInTheDocument();
    expect(screen.getByText("juan@example.com")).toBeInTheDocument();
    expect(screen.getByText("+34600000000")).toBeInTheDocument();
    expect(screen.getByText("Quiero un presupuesto para mi cocina.")).toBeInTheDocument();
  });

  it("leads: a lead with no phone omits it without showing a placeholder", async () => {
    const user = userEvent.setup();
    await createReformaBusiness(user, REFORMA_WORKFLOW_PREVIEW, null, null, [
      {
        id: "lead-1",
        business_id: "biz-reforma",
        source: "website_form",
        name: "Ana Ruiz",
        email: "ana@example.com",
        phone: null,
        message: null,
        status: "new",
        created_at: "2026-08-28T10:00:00Z",
      },
    ]);

    expect(await screen.findByText("Ana Ruiz")).toBeInTheDocument();
    expect(screen.getByText("ana@example.com")).toBeInTheDocument();
    expect(screen.queryByText("null")).not.toBeInTheDocument();
  });

  it("leads: shows each lead's status and changing it calls the real PATCH status API", async () => {
    const user = userEvent.setup();
    await createReformaBusiness(user, REFORMA_WORKFLOW_PREVIEW, null, null, [
      {
        id: "lead-1",
        business_id: "biz-reforma",
        source: "website_form",
        name: "Juan Perez",
        email: "juan@example.com",
        phone: null,
        message: null,
        status: "new",
        created_at: "2026-08-28T10:00:00Z",
      },
    ]);
    await screen.findByText("Juan Perez");
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select.value).toBe("new");

    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, {
        id: "lead-1",
        business_id: "biz-reforma",
        source: "website_form",
        name: "Juan Perez",
        email: "juan@example.com",
        phone: null,
        message: null,
        status: "contacted",
        created_at: "2026-08-28T10:00:00Z",
      }),
    );

    await user.selectOptions(select, "contacted");

    await waitFor(() => expect(select.value).toBe("contacted"));
    const patchCall = fetchMock.mock.calls.find(([, init]) => (init as RequestInit).method === "PATCH");
    expect(patchCall).toBeDefined();
    const [patchUrl, patchInit] = patchCall as [string, RequestInit];
    expect(patchUrl).toContain("/businesses/biz-reforma/leads/lead-1/status");
    expect(JSON.parse(patchInit.body as string)).toEqual({ status: "contacted" });
  });

  it("leads: a failed status update shows a human error and leaves the status unchanged", async () => {
    const user = userEvent.setup();
    await createReformaBusiness(user, REFORMA_WORKFLOW_PREVIEW, null, null, [
      {
        id: "lead-1",
        business_id: "biz-reforma",
        source: "website_form",
        name: "Juan Perez",
        email: "juan@example.com",
        phone: null,
        message: null,
        status: "new",
        created_at: "2026-08-28T10:00:00Z",
      },
    ]);
    await screen.findByText("Juan Perez");
    const select = screen.getByRole("combobox") as HTMLSelectElement;

    fetchMock.mockResolvedValueOnce(
      jsonResponse(404, { error: { code: "lead_not_found", message: "Lead not found." } }),
    );

    await user.selectOptions(select, "lost");

    expect(await screen.findByText("Lead not found.")).toBeInTheDocument();
    expect(select.value).toBe("new");
  });

  it("leads: a failed fetch shows a human error, not a crash", async () => {
    fetchMock.mockResolvedValueOnce(minimalAnalysis(exampleReformaValenciaConfig));
    fetchMock.mockResolvedValueOnce(automationRecommendationResponse());
    fetchMock.mockResolvedValueOnce(
      jsonResponse(201, {
        id: "biz-reforma",
        name: exampleReformaValenciaConfig.business_profile.name,
        slug: exampleReformaValenciaConfig.business_profile.slug,
        status: "draft",
        raw_description: BRIEFING,
        config: exampleReformaValenciaConfig,
      }),
    );
    fetchMock.mockResolvedValueOnce(jsonResponse(200, REFORMA_WORKFLOW_PREVIEW));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, null));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, null));
    fetchMock.mockResolvedValueOnce(
      jsonResponse(500, { error: { code: "internal_error", message: "Something went wrong." } }),
    );
    const user = userEvent.setup();
    renderPage();

    await analyze(user);
    await user.click(await screen.findByRole("button", { name: "Create business" }));

    expect(await screen.findByText(/Could not load leads/)).toBeInTheDocument();
  });
});

describe("NewBusiness reopening an existing business (Studio dashboard's Open action)", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function reformaBusinessResponse() {
    return jsonResponse(200, {
      id: "biz-reforma-pepe",
      name: exampleReformaValenciaConfig.business_profile.name,
      slug: exampleReformaValenciaConfig.business_profile.slug,
      status: "active",
      raw_description: "Empresa de reformas integrales en Valencia.",
      config: exampleReformaValenciaConfig,
    });
  }

  it("shows a loading state while the business is being fetched", () => {
    fetchMock.mockReturnValueOnce(new Promise(() => {})); // never resolves during this test
    renderReopenPage("biz-reforma-pepe");

    expect(screen.getByText("Loading business…")).toBeInTheDocument();
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/businesses/biz-reforma-pepe");
  });

  it("loads the business straight into the existing PreviewStep flow — no separate management UI, no manual UUID entry", async () => {
    fetchMock.mockResolvedValueOnce(reformaBusinessResponse());
    fetchMock.mockResolvedValueOnce(jsonResponse(200, REFORMA_WORKFLOW_PREVIEW));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, null)); // automation state: never activated
    fetchMock.mockResolvedValueOnce(jsonResponse(200, null)); // website state: never published
    fetchMock.mockResolvedValueOnce(jsonResponse(200, [])); // leads: none captured yet
    fetchMock.mockResolvedValueOnce(jsonResponse(200, null)); // custom domain: never attached
    fetchMock.mockResolvedValueOnce(jsonResponse(200, [])); // website versions: none yet
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { checks: [], has_blocking_issues: false })); // production readiness

    renderReopenPage("biz-reforma-pepe");

    expect(
      await screen.findByText(new RegExp(`Business "${exampleReformaValenciaConfig.business_profile.name}" created`)),
    ).toBeInTheDocument();
    // Same PreviewStep affordances a freshly-created business gets —
    // publish/activate/leads are all reachable from here, once their
    // own (mocked) persisted-state reads have resolved.
    expect(await screen.findByRole("button", { name: "Publish website" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Activate automation" })).toBeInTheDocument();
    // Never called POST /businesses or PUT /businesses/{id} just to view it.
    expect(
      fetchMock.mock.calls.every(([, init]) => (init as RequestInit | undefined)?.method !== "POST"),
    ).toBe(true);
    expect(
      fetchMock.mock.calls.every(([, init]) => (init as RequestInit | undefined)?.method !== "PUT"),
    ).toBe(true);
  });

  it("a business that doesn't exist for this tenant shows a friendly error and a way back, not a crash", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(404, { error: { code: "business_not_found", message: "Business not found." } }),
    );

    renderReopenPage("unknown-business-id");

    expect(await screen.findByText("Could not load this business")).toBeInTheDocument();
    expect(screen.getByText("Business not found.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "← Back to businesses" })).toHaveAttribute("href", "/");
  });

  it("reopened business's automation/website reflect the backend's persisted state, not BusinessConfig", async () => {
    fetchMock.mockResolvedValueOnce(reformaBusinessResponse());
    fetchMock.mockResolvedValueOnce(jsonResponse(200, REFORMA_WORKFLOW_PREVIEW));
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, {
        workflow_id: "reforma-casa-valencia-lead-capture",
        remote_id: "42",
        name: REFORMA_WORKFLOW_PREVIEW.name,
        status: "active",
        active: true,
        version: 1,
        required_capabilities: REFORMA_WORKFLOW_PREVIEW.required_capabilities,
        activated_at: "2026-08-27T00:00:00Z",
        updated_at: "2026-08-27T00:00:00Z",
      }),
    );
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, {
        status: "live",
        live_url: "https://site-reforma-pepe.workers.dev/",
        deployment_id: "site-biz-reforma-pepe",
        deployed_at: "2026-08-27T00:00:00Z",
        updated_at: "2026-08-27T00:00:00Z",
      }),
    );
    fetchMock.mockResolvedValueOnce(jsonResponse(200, []));

    renderReopenPage("biz-reforma-pepe");

    expect(await screen.findByText(/Active/)).toBeInTheDocument();
    expect(screen.getByText(/Published/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open live website" })).toHaveAttribute(
      "href",
      "https://site-reforma-pepe.workers.dev/",
    );
  });

  it("the existing New Business flow at /businesses/new is unaffected — no reopen fetch fires there", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, { proposed_config: null, missing_information: [], questions: [] }),
    );
    const user = userEvent.setup();
    renderPage();

    expect(screen.queryByText("Loading business…")).not.toBeInTheDocument();
    await analyze(user);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/businesses/analyze");
  });
});
