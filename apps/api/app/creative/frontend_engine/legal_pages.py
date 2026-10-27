"""Engine-authored legal pages (privacy/terms/cookies) for a generative
build — never AI-authored, for the same "no invented legal facts"
discipline packages/website-generator/src/legal.ts already applies to
the deterministic engine (see that module's own `NOT_PROVIDED`
constant). Guarantees `validate_platform_contract`'s
`missing_legal_page` check always passes for a generative site
regardless of what the AI Frontend Engineer produced, the same way the
deterministic engine's `generateSiteConfig()` always adds all three.

v0.2 R1: rendered from BusinessTruth.legal — legal name, registered
address, registration number, tax ID, privacy contact and data processors
(parity with legal.ts). Anything missing is stated as "not provided";
the trading name is never substituted for the legal name. Every value is
HTML-escaped and Astro-expression-escaped, since it is business-supplied
text written into an .astro template.

Assumes `src/layouts/Layout.astro` exists with a `{title, description}`
Props interface and a `<slot />` — the AI Frontend Engineer's system
prompt (app.creative.frontend_engine.anthropic_engine) requires it to
create exactly that file, the one fixed structural convention this
engine asks of otherwise-bespoke generated output.
"""

import html

from app.domain.business_truth import AddressTruth, BusinessTruth

NOT_PROVIDED = "not provided"


def _text(value: str) -> str:
    """Safe inside an Astro template: HTML-escaped, and `{`/`}` escaped so
    business text can never become an Astro expression."""
    return html.escape(value, quote=True).replace("{", "&#123;").replace("}", "&#125;")


def _or_missing(value: str | None) -> str:
    return value if value else NOT_PROVIDED


def _address(address: AddressTruth | None) -> str:
    if address is None:
        return NOT_PROVIDED
    parts = [address.street_address, address.locality, address.region, address.postal_code, address.country]
    return ", ".join(part for part in parts if part and part.strip())


def _page(title: str, business_name: str, body_paragraphs: list[str]) -> str:
    paragraphs = "\n".join(f"      <p>{_text(paragraph)}</p>" for paragraph in body_paragraphs)
    title_attr = _text(f"{title} — {business_name}")
    description_attr = _text(f"{title} for {business_name}")
    return f"""---
import Layout from "../layouts/Layout.astro";
---
<Layout title="{title_attr}" description="{description_attr}">
  <main>
    <h1>{_text(title)}</h1>
{paragraphs}
  </main>
</Layout>
"""


NOT_PROVIDED_ES = "no facilitado"
LEGAL_LOCALES = ("en", "es")


def legal_owner_input_required(business_truth: BusinessTruth) -> list[str]:
    """H1.2: the legal identity data a published site states, missing from
    BusinessTruth — rendered as "not provided" and reported to the owner.
    A page existing is never treated as legal compliance."""
    legal = business_truth.legal
    missing = []
    if not legal.legal_name:
        missing.append("legal.legal_name")
    if not legal.tax_id:
        missing.append("legal.tax_id")
    if legal.registered_address is None:
        missing.append("legal.registered_address")
    if not (legal.privacy_contact_email or business_truth.contact.email):
        missing.append("legal.privacy_contact_email")
    return missing


def _legal_page_content_es(
    business_truth: BusinessTruth, third_parties: tuple[str, ...], technical_storage: tuple[str, ...] = ()
) -> dict[str, tuple[str, list[str]]]:
    name = business_truth.identity.name
    legal = business_truth.legal

    def given(value: str | None) -> str:
        return value if value else NOT_PROVIDED_ES

    address = NOT_PROVIDED_ES if legal.registered_address is None else _address(legal.registered_address)
    email = legal.privacy_contact_email or business_truth.contact.email or NOT_PROVIDED_ES
    processors = (
        ", ".join(legal.data_processors)
        if legal.data_processors
        else "No se han indicado encargados del tratamiento para este negocio."
    )
    # C3: "Titular" (a person or a company), never "Razón social" and never the
    # trading name; registry data only when the owner supplied it (legal-es.ts).
    identity = [
        f"Titular: {given(legal.legal_name)}.",
        f"NIF: {given(legal.tax_id)}.",
        f"Domicilio: {address}.",
        *([f"Datos registrales: {legal.registration_number}."] if legal.registration_number else []),
    ]
    legal_basis = (
        "tu consentimiento, que prestas al marcar la casilla del formulario. Puedes retirarlo en cualquier "
        "momento escribiendo al correo electrónico indicado."
        if legal.consent_required
        else f"{NOT_PROVIDED_ES}."
    )
    return {
        "privacy": (
            "Política de privacidad",
            [
                f"Este sitio web presenta la actividad de {name}.",
                *identity,
                # P3: what really happens to a contact message — never "analytics" or advertising.
                "Si escribes a través del formulario de contacto, los datos que envías (tu nombre, tu email, tu "
                "mensaje y los demás campos que rellenes) se usan solo para responder a tu mensaje. No se usan "
                "para publicidad ni para estadísticas.",
                "Tu mensaje se guarda en la plataforma que aloja este sitio y se envía por email al titular para "
                "que pueda responderte. Puedes recibir un email automático que confirma su recepción.",
                f"Base jurídica: {legal_basis}",
                f"Plazo de conservación: {given(legal.data_retention)}.",
                f"Encargados del tratamiento: {processors}",
                f"Contacto para cuestiones de privacidad y para ejercer tus derechos: {email}.",
                "Puedes solicitar el acceso, la rectificación o la supresión de tus datos, así como la limitación "
                "u oposición a su tratamiento y su portabilidad, escribiendo a ese correo. También puedes presentar "
                "una reclamación ante la Agencia Española de Protección de Datos (www.aepd.es).",
            ],
        ),
        "terms": (
            "Aviso legal",
            [
                f"Este sitio web presenta la actividad de {name}.",
                *identity,
                f"Contacto: {email}.",
                "Al usar este sitio aceptas utilizarlo de forma lícita y no hacer un uso indebido del formulario "
                "de contacto.",
            ],
        ),
        "cookies": (
            "Política de cookies",
            [
                "Necesario: tu elección sobre el aviso de privacidad se guarda en el almacenamiento local del "
                "navegador (clave «gwa-consent») para no volver a preguntarte.",
                *(f"Almacenamiento técnico: {item}" for item in technical_storage),
                "Analítica (opcional): solo si la aceptas, el sitio envía a sus propios servidores qué página se "
                "visita, cuándo y qué enlaces de contacto se pulsan, sin cookies y sin identificadores personales. "
                "Sin tu permiso no se envía nada.",
                "Puedes cambiar o retirar tu consentimiento en cualquier momento desde «Preferencias de cookies», "
                "al pie de cada página.",
                *(f"Servicio de terceros: {service}" for service in third_parties),
            ],
        ),
    }


def legal_page_content(
    business_truth: BusinessTruth,
    *,
    locale: str = "en",
    third_parties: tuple[str, ...] = (),
    technical_storage: tuple[str, ...] = (),
) -> dict[str, tuple[str, list[str]]]:
    """{slug: (title, paragraphs)} for privacy/terms/cookies as PLAIN,
    unescaped text — the single source of the legal wording. Rendered by
    build_legal_pages (Astro) and by app.creative.source_adapter, which
    renders the same wording inside an exported site's own framework.
    `locale` (H1.2): "en" (default, unchanged) or "es". `third_parties`:
    trusted descriptions of third-party services the site's source family
    loads (disclosed on the cookie page). `technical_storage` (P3): trusted
    descriptions of the browser storage the family's own framework uses."""
    if locale not in LEGAL_LOCALES:
        raise ValueError(f"no legal wording for locale {locale!r}")
    if locale == "es":
        return _legal_page_content_es(business_truth, third_parties, technical_storage)
    name = business_truth.identity.name
    legal = business_truth.legal
    privacy_email = legal.privacy_contact_email or business_truth.contact.email or NOT_PROVIDED
    processors = (
        ", ".join(legal.data_processors)
        if legal.data_processors
        else "No third-party data processors have been listed for this business."
    )

    return {
        "privacy": (
            "Privacy Policy",
            [
                f"This website is operated by {name}.",
                f"Legal name: {_or_missing(legal.legal_name)}.",
                f"Registered address: {_address(legal.registered_address)}.",
                f"Registration number: {_or_missing(legal.registration_number)}.",
                f"Tax ID: {_or_missing(legal.tax_id)}.",
                "If you write through the contact form, the information you send (your name, email, message and "
                "any other field you fill in) is used only to reply to your message. It is not used for "
                "advertising or for statistics.",
                "Your message is stored on the platform that hosts this site and emailed to the site owner so "
                "they can reply. You may receive an automatic email confirming it arrived.",
                f"Third parties we work with: {processors}",
                f"Contact for privacy questions: {privacy_email}.",
            ],
        ),
        "terms": (
            "Terms of Service",
            [
                f"These terms govern use of this website operated by {name} "
                f"(legal name: {_or_missing(legal.legal_name)}). By using this site you agree to use it "
                "lawfully and not to misuse any contact or lead-capture functionality it provides.",
                f"Questions about these terms can be sent to {privacy_email}.",
            ],
        ),
        "cookies": (
            "Cookie Policy",
            [
                "Necessary: your choice on the privacy notice is kept in the browser's local storage (key "
                '"gwa-consent") so you are not asked again.',
                *(f"Technical storage: {item}" for item in technical_storage),
                "Analytics (optional): only if you accept it, the site sends its own servers which page is "
                "visited, when, and which contact links are clicked, without cookies and without personal "
                "identifiers. Without your permission nothing is sent.",
                "You can change or withdraw your choice at any time from the privacy preferences link in "
                "the footer.",
                *(f"Third-party service: {service}" for service in third_parties),
            ],
        ),
    }


def build_legal_pages(business_truth: BusinessTruth) -> dict[str, str]:
    """Returns {relative_astro_page_path: content} for /privacy, /terms,
    /cookies — written into the workspace by the same engine code path
    that writes the AI's own manifest, at fixed paths the AI's manifest
    is never allowed to touch (workspace.py rejects any AI-submitted
    file whose path collides, since these are always written last)."""
    name = business_truth.identity.name
    return {
        f"src/pages/{slug}.astro": _page(title, name, paragraphs)
        for slug, (title, paragraphs) in legal_page_content(business_truth).items()
    }
