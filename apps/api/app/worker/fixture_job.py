"""v0.2 R4.2 — controlled infrastructure E2E: one deterministic job.

    python -m app.worker.fixture_job --tenant-id T --business-id B \\
        --api-base-url https://api.example.com            # dry run
    ... --confirm                                          # enqueue

Queues ONE generative build whose source is produced deterministically from
the business's own BusinessTruth by this module — no provider call, no
Anthropic, no Higgsfield. The external worker then builds it in the sandbox,
runs sandboxed Visual QA and returns a candidate; the trusted intake judges
it like any other (PlatformContract, TruthContract, private storage, READY).
It never approves, publishes or touches the live site, and it neither needs
nor changes the S0 gate. Run it inside the API's own environment (database
and private storage come from its settings).
"""

import argparse
import html
import re
import sys
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.creative.frontend_engine.legal_pages import build_legal_pages
from app.db.models.generative_website_artifact import GenerativeWebsiteArtifact
from app.db.models.website_draft import WebsiteDraft
from app.domain.business_truth import BusinessTruth
from app.domain.enums import AssetKind, GenerationEngine, WebsiteDraftStatus
from app.qa.platform_contract import PLATFORM_CONTRACT_VERSION
from app.storage.private import PrivateArtifactStorage
from app.worker import intake
from app.worker.protocol import sha256_hex

FIXTURE_PROVIDER = "r4-infrastructure-fixture"


def _t(value: str) -> str:
    return html.escape(value, quote=True).replace("{", "&#123;").replace("}", "&#125;")


def fixture_source(truth: BusinessTruth) -> dict[str, bytes]:
    """A minimal, platform-complete site in which every fact comes from
    BusinessTruth: lead form (platform SDK), legal links, consent control,
    and the business's own optional logo/photo/services/reviews/contacts."""
    parts: list[str] = []
    if truth.logo is not None:
        parts.append(f'<img src="{_t(truth.logo.url)}" alt="{_t(truth.logo.alt_text or truth.identity.name)}" />')
    photo = next((a for a in truth.assets if a.is_real and a.kind is AssetKind.IMAGE), None)
    if photo is not None:
        parts.append(f'<img src="{_t(photo.url)}" alt="{_t(photo.alt_text or "")}" />')
    services = "".join(f"<li>{_t(s.name)}</li>" for s in truth.services)
    if services:
        parts.append(f"<ul>{services}</ul>")
    for review in truth.reviews:
        cite = f"<cite>{_t(review.author_name)}</cite>" if review.author_name else ""
        parts.append(f"<blockquote><p>{_t(review.body)}</p>{cite}</blockquote>")
    contacts: list[str] = []
    if truth.contact.phone:
        contacts.append(f'<a href="tel:{re.sub(r"[^0-9+]", "", truth.contact.phone)}">{_t(truth.contact.phone)}</a>')
    if truth.contact.email:
        contacts.append(f'<a href="mailto:{_t(truth.contact.email)}">{_t(truth.contact.email)}</a>')
    if truth.contact.whatsapp is not None:
        digits = re.sub(r"[^0-9]", "", truth.contact.whatsapp.phone_number)
        contacts.append(f'<a href="https://wa.me/{digits}">WhatsApp</a>')
    if contacts:
        parts.append("<p>" + " · ".join(contacts) + "</p>")
    body = "\n    ".join(parts)
    name = _t(truth.identity.name)
    description = _t(truth.description.description or truth.identity.name)
    layout = """---
export interface Props { title: string; description: string; }
const { title, description } = Astro.props;
---
<html lang="es">
  <head>
    <meta charset="utf-8" />
    <title>{title}</title>
    <meta name="description" content={description} />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
  </head>
  <body>
    <slot />
    <script>import "../lib/platform-sdk";</script>
  </body>
</html>
"""
    index = f"""---
import Layout from "../layouts/Layout.astro";
---
<Layout title="{name}" description="{description}">
  <main>
    <h1>{name}</h1>
    {body}
    <form data-gwa-lead-form>
      <input name="name" aria-label="Nombre" />
      <input name="email" type="email" aria-label="Email" />
      <textarea name="message" aria-label="Mensaje"></textarea>
      <label><input type="checkbox" name="consent" value="true" /> Acepto la política</label>
      <button type="submit">Enviar</button>
    </form>
    <p><a href="/privacy">Privacidad</a> · <a href="/terms">Condiciones</a> · <a href="/cookies">Cookies</a>
      <button type="button" data-open-consent-preferences>Cookies</button></p>
  </main>
  <script>
    import {{ submitLead }} from "../lib/platform-sdk";
    const form = document.querySelector<HTMLFormElement>("form[data-gwa-lead-form]");
    form?.addEventListener("submit", async (event) => {{
      event.preventDefault();
      const ok = await submitLead(Object.fromEntries(new FormData(form)) as Record<string, string>);
      form.setAttribute("data-status", ok ? "sent" : "failed");
    }});
  </script>
</Layout>
"""
    files = {"src/layouts/Layout.astro": layout.encode("utf-8"), "src/pages/index.astro": index.encode("utf-8")}
    files.update({path: content.encode("utf-8") for path, content in build_legal_pages(truth).items()})
    return files


def enqueue_fixture_job(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    business_id: uuid.UUID,
    artifact_storage: PrivateArtifactStorage,
    api_base_url: str,
) -> tuple[WebsiteDraft, uuid.UUID]:
    _, truth = intake.load_business_inputs(session, tenant_id=tenant_id, business_id=business_id)
    draft = WebsiteDraft(
        tenant_id=tenant_id,
        business_id=business_id,
        engine=GenerationEngine.GENERATIVE,
        site_config=None,
        status=WebsiteDraftStatus.BUILDING,
    )
    session.add(draft)
    session.flush()
    job = intake.enqueue_generative_build(
        session,
        draft=draft,
        source_files=fixture_source(truth),
        idempotency_key=f"r4-fixture-{draft.id}",
        input_sha256=sha256_hex(truth.canonical_json().encode("utf-8")),
        artifact_storage=artifact_storage,
        api_base_url=api_base_url,
    )
    session.add(
        GenerativeWebsiteArtifact(
            tenant_id=tenant_id,
            business_id=business_id,
            website_draft_id=draft.id,
            creative_direction_id=None,
            framework="astro",
            workspace_key=job.source_key or "",
            build_command="isolated worker",
            output_dir="dist",
            dependencies=[],
            platform_contract_version=PLATFORM_CONTRACT_VERSION,
            qa_state={},
            generator_provider=FIXTURE_PROVIDER,
            generator_model=None,
            generated_at=datetime.now(UTC),
            duration_ms=None,
        )
    )
    session.flush()
    return draft, job.id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.worker.fixture_job")
    parser.add_argument("--tenant-id", type=uuid.UUID, required=True)
    parser.add_argument("--business-id", type=uuid.UUID, required=True)
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--confirm", action="store_true", help="actually enqueue (default: dry run)")
    args = parser.parse_args(argv)

    from app.config import settings
    from app.db.session import make_engine, make_session_factory
    from app.dependencies import get_private_artifact_storage

    engine = make_engine(settings.database_url)
    session = make_session_factory(engine)()
    try:
        if not args.confirm:
            _, truth = intake.load_business_inputs(session, tenant_id=args.tenant_id, business_id=args.business_id)
            source = fixture_source(truth)
            print(f"DRY RUN: {len(source)} fixture source files derived; nothing written (pass --confirm).")
            return 0
        draft, job_id = enqueue_fixture_job(
            session,
            tenant_id=args.tenant_id,
            business_id=args.business_id,
            artifact_storage=get_private_artifact_storage(),
            api_base_url=args.api_base_url,
        )
        session.commit()
        print(f"R4_FIXTURE_JOB_QUEUED job_id={job_id} draft_id={draft.id}")
        return 0
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
