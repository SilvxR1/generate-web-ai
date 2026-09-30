"""TruthContract (v0.2 R3) — WHAT THE WEBSITE MAY CLAIM.

    BusinessTruth    — what the platform knows       (app.domain.business_truth)
    PlatformContract — what the website must do      (app.qa.platform_contract)
    TruthContract    — what the website may claim    (this module)

    Generated websites may transform presentation, but may not expand
    business truth. Missing business information is not permission to
    invent it.

A deterministic validation of a BUILT artifact's user-visible output (every
HTML page: visible text, link destinations, image sources/alt text,
blockquotes/citations, JSON-LD) plus literal contact data in shipped JS,
against a BusinessTruth. No AI, no provider, no network. It never inspects
layout, section order, typography, colors, component names or composition:
creative/marketing language passes; factual EXPANSION fails.

Scope is deliberately conservative (docs, R3): BLOCKING rules cover the
high-confidence categories (contact destinations, legal identifiers,
reviews/ratings/counts, numeric business claims, rankings, certifications/
awards, street addresses, asset identity); ambiguous marketing language is
ADVISORY; arbitrary semantic deception and service-area wording are NOT YET
ENFORCEABLE. Content generated JavaScript would insert at runtime is only
checked for literal emails/WhatsApp destinations in the shipped JS.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from html.parser import HTMLParser

from pydantic import BaseModel, ConfigDict, Field

from app.domain.business_truth import BusinessTruth

TRUTH_CONTRACT_VERSION = "1.0.0"


class TruthSeverity(StrEnum):
    BLOCKING = "blocking"
    ADVISORY = "advisory"


class TruthCategory(StrEnum):
    CONTACT = "contact"
    LEGAL = "legal"
    REVIEWS = "reviews"
    CLAIMS = "claims"
    LOCATION = "location"
    ASSETS = "assets"


class TruthViolation(BaseModel):
    """Safe and structured: a stable rule id and a short fixed description —
    never the offending customer content or anything secret."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule: str
    category: TruthCategory
    severity: TruthSeverity
    path: str
    description: str


class TruthContractResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = TRUTH_CONTRACT_VERSION
    findings: list[TruthViolation] = Field(default_factory=list)

    @property
    def violations(self) -> list[TruthViolation]:
        return [f for f in self.findings if f.severity is TruthSeverity.BLOCKING]

    @property
    def warnings(self) -> list[TruthViolation]:
        return [f for f in self.findings if f.severity is TruthSeverity.ADVISORY]

    @property
    def passed(self) -> bool:
        return not self.violations

    def summary(self) -> str:
        """Safe one-line summary for draft errors/logs: rule ids + pages only."""
        return "; ".join(f"{v.rule} ({v.path})" for v in self.violations)


# --- Normalization ---------------------------------------------------------------


def _norm_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).lower()
    value = re.sub(r"[\"“”«»‘’'`]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _digits(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    return digits[2:] if digits.startswith("00") else digits


def _same_phone(a: str, b: str) -> bool:
    """Formatting-insensitive; tolerates a short country-code prefix on one
    side (+34 600 000 000 vs 600 000 000) but never a different number."""
    da, db = _digits(a), _digits(b)
    if not da or not db:
        return False
    if da == db:
        return True
    short, long_ = sorted((da, db), key=len)
    return len(short) >= 9 and long_.endswith(short) and len(long_) - len(short) <= 3


def _number(value: str) -> float | None:
    compact = value.replace(" ", "").rstrip(".,")
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", compact):  # 1.000 / 1,000 → thousands separator
        compact = re.sub(r"[.,]", "", compact)
    try:
        return float(compact.replace(",", "."))
    except ValueError:
        return None


# --- Rendered-output extraction ------------------------------------------------------


@dataclass
class _Image:
    src: str
    alt: str
    logo_hint: bool


@dataclass
class _Quote:
    text: str


@dataclass
class _Page:
    path: str
    text: list[str] = field(default_factory=list)
    hrefs: list[str] = field(default_factory=list)
    images: list[_Image] = field(default_factory=list)
    quotes: list[_Quote] = field(default_factory=list)
    cites: list[str] = field(default_factory=list)
    json_ld: list[str] = field(default_factory=list)
    css: list[str] = field(default_factory=list)

    @property
    def visible(self) -> str:
        return "\n".join(self.text)


_SKIP_TAGS = {"script", "style", "template", "svg"}


class _Extractor(HTMLParser):
    def __init__(self, page: _Page) -> None:
        super().__init__(convert_charrefs=True)
        self.page = page
        self.skip = 0
        self.ld_json = False
        self.style = False
        self.quote_depth = 0
        self.quote_buf: list[str] = []
        self.cite_depth = 0
        self.cite_buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self.ld_json = True
        if tag == "style":
            self.style = True
        if tag in _SKIP_TAGS:
            self.skip += 1
        if tag == "a" and a.get("href"):
            self.page.hrefs.append(a["href"].strip())
        if tag == "img":
            hints = " ".join([a.get("alt", ""), a.get("class", ""), a.get("id", ""), *a])
            self.page.images.append(_Image(a.get("src", "").strip(), a.get("alt", ""), "logo" in hints.lower()))
        if tag == "meta" and a.get("name", "").lower() == "description" and a.get("content"):
            self.page.text.append(a["content"])
        for attr in ("alt", "title", "aria-label"):
            if a.get(attr) and tag != "script":
                self.page.text.append(a[attr])
        if a.get("style") and "url(" in a["style"]:
            self.page.css.append(a["style"])
        if tag in ("blockquote", "q"):
            self.quote_depth += 1
        if tag == "cite":
            self.cite_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self.skip:
            self.skip -= 1
        if tag == "script":
            self.ld_json = False
        if tag == "style":
            self.style = False
        if tag == "cite" and self.cite_depth:
            self.cite_depth -= 1
            cite = " ".join(self.cite_buf).strip()
            self.cite_buf = []
            if cite:
                self.page.cites.append(cite)
        if tag in ("blockquote", "q") and self.quote_depth:
            self.quote_depth -= 1
            if not self.quote_depth:
                self.page.quotes.append(_Quote(" ".join(self.quote_buf).strip()))
                self.quote_buf = []

    def handle_data(self, data: str) -> None:
        if self.ld_json:
            self.page.json_ld.append(data)
            return
        if self.style:
            self.page.css.append(data)
            return
        if self.skip:
            return
        text = data.strip()
        if not text:
            return
        self.page.text.append(text)
        if self.cite_depth:
            self.cite_buf.append(text)
        elif self.quote_depth:
            self.quote_buf.append(text)


def _pages(files: dict[str, bytes]) -> list[_Page]:
    pages = []
    for path in sorted(files):
        if not path.endswith(".html"):
            continue
        page = _Page(path)
        _Extractor(page).feed(files[path].decode("utf-8", errors="ignore"))
        pages.append(page)
    return pages


# --- BusinessTruth-derived allowlists ------------------------------------------------


@dataclass
class _Allow:
    phones: list[str]
    emails: set[str]
    whatsapp: set[str]
    corpus: str  # normalized factual text from BusinessTruth
    numbers: set[float]
    identifiers: set[str]
    legal_name: str | None
    addresses: list[str]
    review_bodies: list[str]
    authors: set[str]
    ratings: set[float]
    review_count: int
    asset_urls: dict[str, bool]  # url -> is_real
    logo_url: str | None
    website: str | None


def _truth_texts(truth: BusinessTruth) -> list[str]:
    texts = [truth.identity.name, truth.identity.tagline or "", truth.description.description or ""]
    texts.append(truth.description.target_customers or "")
    for s in truth.services:
        texts += [s.name, s.description, s.short_description or "", s.category or ""]
        if s.price_from is not None:
            texts.append(f"{s.price_from:g}")
    loc = truth.location
    texts += [loc.city or "", loc.region or "", loc.postal_code or "", *loc.service_area]
    for address in (truth.contact.address, truth.legal.registered_address):
        if address:
            texts += [address.street_address, address.locality, address.region or "", address.postal_code or ""]
    for rule in truth.opening_hours:
        texts += [rule.opens, rule.closes]
    legal = truth.legal
    texts += [legal.legal_name or "", legal.registration_number or "", legal.tax_id or ""]
    for review in truth.reviews:
        texts += [review.body, review.author_name or ""]
    return [t for t in texts if t]


def _allow(truth: BusinessTruth) -> _Allow:
    corpus = _norm_text(" \n ".join(_truth_texts(truth)))
    numbers = {n for token in re.findall(r"\d[\d.,]*", corpus) if (n := _number(token)) is not None}
    phones = [p for p in (truth.contact.phone, truth.contact.whatsapp_contact) if p]
    whatsapp = {_digits(truth.contact.whatsapp_contact)} if truth.contact.whatsapp_contact else set()
    if truth.contact.whatsapp:
        phones.append(truth.contact.whatsapp.phone_number)
        whatsapp.add(_digits(truth.contact.whatsapp.phone_number))
    emails = {e.lower() for e in (truth.contact.email, truth.legal.privacy_contact_email) if e}
    identifiers = {
        re.sub(r"[^A-Z0-9]", "", i.upper()) for i in (truth.legal.registration_number, truth.legal.tax_id) if i
    }
    addresses = [
        _norm_text(a.street_address) for a in (truth.contact.address, truth.legal.registered_address) if a is not None
    ]
    rated = [float(r.rating) for r in truth.reviews if r.rating is not None]
    ratings = set(rated)
    if rated:
        average = sum(rated) / len(rated)
        ratings |= {round(average, 1), round(average, 2)}
    return _Allow(
        phones=phones,
        emails=emails,
        whatsapp={w for w in whatsapp if w},
        corpus=corpus,
        numbers=numbers,
        identifiers=identifiers,
        legal_name=_norm_text(truth.legal.legal_name).rstrip(".") if truth.legal.legal_name else None,
        addresses=addresses,
        review_bodies=[_norm_text(r.body) for r in truth.reviews],
        authors={_norm_text(r.author_name) for r in truth.reviews if r.author_name},
        ratings=ratings,
        review_count=len(truth.reviews),
        asset_urls={a.url: a.is_real for a in truth.assets},
        logo_url=truth.logo.url if truth.logo else None,
        website=truth.contact.website,
    )


# --- Patterns (Spanish + English; conservative, high-confidence) ---------------------------

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_TEXT = re.compile(r"(?<![\w/#.-])\+?\(?\d[\d\s().-]{7,}\d(?![\w/])")
_WA = re.compile(r"(?:wa\.me/|api\.whatsapp\.com/send\?phone=)(\d+)")
# A string literal assigned to a `placeholder` prop/attribute in shipped JS
# (compiled JSX `placeholder:"…"`, `placeholder="…"`, `.placeholder = "…"`).
_PLACEHOLDER_VALUE = re.compile(r"""\bplaceholder\s*[:=]\s*(["'`])([^"'`\\\n]*)\1""")
_SOCIAL = re.compile(
    r"^https?://(?:www\.)?(?:facebook\.com|instagram\.com|x\.com|twitter\.com|linkedin\.com|tiktok\.com|"
    r"youtube\.com|pinterest\.com)/",
    re.IGNORECASE,
)
_LEGAL_NAME = re.compile(r"(?:legal name|raz[oó]n social|denominaci[oó]n social)\s*:\s*([^\n<);]{1,160})", re.I)
_TAX_ID = re.compile(
    r"(?:tax id|vat(?: number| id)?|n\.?i\.?f\.?|c\.?i\.?f\.?)\s*:?\s*((?=[A-Z0-9-]*\d)[A-Z0-9-]{6,20})\b", re.I
)
_REG_NUMBER = re.compile(
    r"(?:registration number|company number|n[úu]mero de registro|registro mercantil)\s*:?\s*"
    r"((?=[A-Z0-9/-]*\d)[A-Z0-9/-]{4,30})\b",
    re.I,
)
_REG_ADDRESS = re.compile(
    r"(?:registered address|domicilio social|direcci[oó]n registrada)\s*:\s*([^\n<);]{3,200})", re.I
)
_NOT_PROVIDED = re.compile(r"^(?:not provided|no proporcionad[oa]|no facilitad[oa]|no disponible)\.?$", re.I)
_RATING = re.compile(r"(\d(?:[.,]\d{1,2})?)\s*(?:/\s*5\b|(?:de|out of)\s+5\b|(?:estrellas|stars)\b|★)", re.I)
_STARS = re.compile(r"[★⭐]{3,}")
_REVIEW_COUNT = re.compile(
    r"(\d[\d.,]*)\s*\+?\s*(?:reseñas|resenas|opiniones|valoraciones|reviews|testimonios|testimonials|ratings)\b",
    re.I,
)
_YEARS_EXPERIENCE = re.compile(
    r"(\d{1,3})\s*\+?\s*(?:años|anos|years?)\s+(?:de\s+|of\s+)?"
    r"(?:experiencia|experience|trayectoria|oficio|en el sector|in business|in the industry)",
    re.I,
)
_FOUNDED = re.compile(
    r"(?:desde (?:el (?:año )?)?|since |fundad[ao]s? en |founded in |established in )((?:19|20)\d{2})\b", re.I
)
_COUNT = re.compile(
    r"(\d[\d.,]*)\s*\+?\s*(?:[a-záéíóúñ]+\s+)?(?:proyectos|projects|obras|reformas|clientes|customers|clients|"
    r"trabajos|jobs|instalaciones|installations|viviendas|homes|familias|families|hogares|pedidos|orders)\b",
    re.I,
)
_PERCENT = re.compile(r"(\d{1,3}(?:[.,]\d+)?)\s*%")
_SATISFACTION_CONTEXT = re.compile(
    r"satisf|clientes|customers|recomiend|recommend|éxito|exito|success|puntual|on[- ]time", re.I
)
_ALWAYS_OPEN = re.compile(r"\b24\s*/\s*7\b|\b24\s*[x×]\s*7\b|\b365\s*d[ií]as\b", re.I)
_FAST = re.compile(r"\b(?:24|48)\s*(?:h|horas|hours)\b", re.I)
_RANK = re.compile(r"(?:#\s?1\b|\bn[ºo°]\.?\s?1\b|\bn[uú]mero\s+(?:1|uno)\b|\bnumber\s+(?:1|one)\b|\bno\.\s?1\b)", re.I)
_CERT = re.compile(
    r"\b(certificad[oa]s?|certified|certificaci[oó]n|certification|acreditad[oa]s?|accredited|"
    r"homologad[oa]s?|iso\s?\d{3,5}|premiad[oa]s?|galardonad[oa]s?|award-winning|awards?|premios?|"
    r"miembros?\s+de|members?\s+of|colegiad[oa]s?|licensed|instaladores?\s+autorizad[oa]s?|"
    r"autorizad[oa]s?\s+por)\b",
    re.I,
)
_SUPERLATIVE = re.compile(r"\b(?:mejor(?:es)?|best|l[ií]der(?:es)?|leading|top)\b", re.I)
_GUARANTEE_NUMBER = re.compile(
    r"(?:(\d{1,3})\s*(?:años|anos|years|meses|months)\s+(?:de\s+)?(?:garant|warrant|guarant))|"
    r"(?:(?:garant[ií]a|guarantee|warranty)\s+(?:de\s+|of\s+)?(\d{1,3})\s*(?:años|anos|years|meses|months))",
    re.I,
)
_GUARANTEE = re.compile(r"\b(?:garant[ií]a|garantizad[oa]s?|guaranteed?|warranty)\b", re.I)
_STREET = re.compile(
    r"\b(?:calle|c/|avda\.?|avenida|plaza|pza\.|paseo|camino|carretera|ronda|street|avenue|road)\s+"
    r"([A-Za-zÁÉÍÓÚÑáéíóúñ0-9][^\n,.;:<]{1,40})",
    re.I,
)
_ENTITY_FORM = re.compile(r"\b(?:S\.L\.U?\.|S\.A\.|SLU\b|Ltd\b|LLC\b|GmbH\b|Inc\.)")
_URL_IN_CSS = re.compile(r"url\(\s*['\"]?(https?://[^'\")\s]+)", re.I)
_REAL_WORK_WORDS = re.compile(
    r"proyecto|obra realizada|trabajo realizado|real project|our work|nuestro trabajo|antes|después|before|after",
    re.I,
)


# --- Rules -----------------------------------------------------------------------------------

B, A = TruthSeverity.BLOCKING, TruthSeverity.ADVISORY


class _Findings:
    def __init__(self) -> None:
        self.items: list[TruthViolation] = []
        self._seen: set[tuple[str, str]] = set()

    def add(self, rule: str, category: TruthCategory, severity: TruthSeverity, path: str, description: str) -> None:
        if (rule, path) in self._seen:
            return  # one finding per rule per page: small, content-free output
        self._seen.add((rule, path))
        self.items.append(
            TruthViolation(rule=rule, category=category, severity=severity, path=path, description=description)
        )


def _supported(allow: _Allow, raw: str) -> bool:
    value = _number(raw)
    return value is not None and value in allow.numbers


def _check_contact(page: _Page, allow: _Allow, out: _Findings) -> None:
    for href in page.hrefs:
        lower = href.lower()
        if lower.startswith("tel:"):
            if not any(_same_phone(href[4:], p) for p in allow.phones):
                out.add(
                    "truth.contact.phone_unauthorized",
                    TruthCategory.CONTACT,
                    B,
                    page.path,
                    "A phone link targets a number that is not in BusinessTruth.",
                )
        elif lower.startswith("mailto:"):
            if href[7:].split("?")[0].strip().lower() not in allow.emails:
                out.add(
                    "truth.contact.email_unauthorized",
                    TruthCategory.CONTACT,
                    B,
                    page.path,
                    "An email link targets an address that is not in BusinessTruth.",
                )
        elif _SOCIAL.match(href) and href.rstrip("/") != (allow.website or "").rstrip("/"):
            out.add(
                "truth.contact.social_link_unsupported",
                TruthCategory.CONTACT,
                B,
                page.path,
                "A social-network link is not a channel recorded in BusinessTruth.",
            )
        for number in _WA.findall(href):
            if _digits(number) not in allow.whatsapp:
                out.add(
                    "truth.contact.whatsapp_unauthorized",
                    TruthCategory.CONTACT,
                    B,
                    page.path,
                    "A WhatsApp link targets a number that is not the business's WhatsApp in BusinessTruth.",
                )
    text = page.visible
    for email in _EMAIL.findall(text):
        if email.lower() not in allow.emails:
            out.add(
                "truth.contact.email_unauthorized",
                TruthCategory.CONTACT,
                B,
                page.path,
                "The page shows an email address that is not in BusinessTruth.",
            )
    for candidate in _PHONE_TEXT.findall(text):
        digits = _digits(candidate)
        if len(digits) < 9 or digits in allow.identifiers:
            continue
        if not any(_same_phone(candidate, p) for p in allow.phones):
            out.add(
                "truth.contact.phone_unauthorized",
                TruthCategory.CONTACT,
                B,
                page.path,
                "The page shows a phone number that is not in BusinessTruth.",
            )


def _check_legal(page: _Page, allow: _Allow, out: _Findings) -> None:
    text = page.visible
    for value in _LEGAL_NAME.findall(text):
        clean = _norm_text(value).rstrip(".").strip()
        if _NOT_PROVIDED.match(clean):
            continue
        if allow.legal_name is None or clean != allow.legal_name:
            out.add(
                "truth.legal.name_mismatch",
                TruthCategory.LEGAL,
                B,
                page.path,
                "A stated legal name does not match BusinessTruth.",
            )
    for pattern in (_TAX_ID, _REG_NUMBER):
        for value in pattern.findall(text):
            if re.sub(r"[^A-Z0-9]", "", value.upper()) not in allow.identifiers:
                out.add(
                    "truth.legal.identifier_mismatch",
                    TruthCategory.LEGAL,
                    B,
                    page.path,
                    "A stated legal identifier (tax/registration number) does not match BusinessTruth.",
                )
    for value in _REG_ADDRESS.findall(text):
        clean = _norm_text(value).rstrip(".")
        if _NOT_PROVIDED.match(clean):
            continue
        if not any(street and street in clean for street in allow.addresses):
            out.add(
                "truth.legal.address_mismatch",
                TruthCategory.LEGAL,
                B,
                page.path,
                "A stated registered address does not match BusinessTruth.",
            )
    if allow.legal_name is None and _ENTITY_FORM.search(text) and not _ENTITY_FORM.search(allow.corpus.upper()):
        out.add(
            "truth.legal.possible_entity",
            TruthCategory.LEGAL,
            A,
            page.path,
            "The page mentions a legal-entity form although BusinessTruth records no legal name.",
        )


def _quote_is_genuine(quote: _Quote, allow: _Allow) -> bool:
    """A quotation must reproduce a real review (optionally with its real
    author/rating) or owner-reviewed text — never a paraphrase or addition."""
    text = _norm_text(quote.text)
    for body in allow.review_bodies:
        if body and body in text:
            remainder = text.replace(body, " ")
            remainder = re.sub(r"\d(?:[.,]\d)?\s*(?:/\s*5|estrellas|stars)?|[★⭐]", " ", remainder)
            for author in allow.authors:
                remainder = remainder.replace(author, " ")
            return len(re.findall(r"[a-záéíóúñ]", remainder)) < 3
    return bool(text) and text in allow.corpus


def _check_reviews(page: _Page, allow: _Allow, out: _Findings) -> None:
    for quote in page.quotes:
        if quote.text and not _quote_is_genuine(quote, allow):
            out.add(
                "truth.reviews.fabricated_quote",
                TruthCategory.REVIEWS,
                B,
                page.path,
                "A quotation/testimonial does not reproduce a real review or owner text from BusinessTruth.",
            )
    for cite in page.cites:
        name = _norm_text(cite)
        if name not in allow.authors and name not in allow.corpus:
            out.add(
                "truth.reviews.fabricated_author",
                TruthCategory.REVIEWS,
                B,
                page.path,
                "A cited customer/author is not a review author in BusinessTruth.",
            )
    text = page.visible
    for raw in _RATING.findall(text):
        if _number(raw) not in allow.ratings:
            out.add(
                "truth.reviews.fabricated_rating",
                TruthCategory.REVIEWS,
                B,
                page.path,
                "A rating is shown that no real review in BusinessTruth supports.",
            )
    for stars in _STARS.findall(text):
        if float(len(stars)) not in allow.ratings:
            out.add(
                "truth.reviews.fabricated_rating",
                TruthCategory.REVIEWS,
                B,
                page.path,
                "A star rating is shown that no real review in BusinessTruth supports.",
            )
    for raw in _REVIEW_COUNT.findall(text):
        if _number(raw) != float(allow.review_count):
            out.add(
                "truth.reviews.fabricated_count",
                TruthCategory.REVIEWS,
                B,
                page.path,
                "A review/testimonial count does not match the reviews in BusinessTruth.",
            )
    for block in page.json_ld:
        lowered = block.lower()
        if ("aggregaterating" in lowered or '"review"' in lowered) and not allow.ratings:
            out.add(
                "truth.reviews.structured_data",
                TruthCategory.REVIEWS,
                B,
                page.path,
                "Structured data declares reviews/ratings that BusinessTruth does not contain.",
            )


def _check_claims(page: _Page, allow: _Allow, out: _Findings) -> None:
    text = page.visible
    for raw in _YEARS_EXPERIENCE.findall(text):
        if not _supported(allow, raw):
            out.add(
                "truth.claims.years_experience",
                TruthCategory.CLAIMS,
                B,
                page.path,
                "Years of experience are claimed that BusinessTruth does not support.",
            )
    for year in _FOUNDED.findall(text):
        if not _supported(allow, year):
            out.add(
                "truth.claims.founding_year",
                TruthCategory.CLAIMS,
                B,
                page.path,
                "A founding/'since' year is claimed that BusinessTruth does not support.",
            )
    for raw in _COUNT.findall(text):
        if not _supported(allow, raw):
            out.add(
                "truth.claims.business_count",
                TruthCategory.CLAIMS,
                B,
                page.path,
                "A project/customer count is claimed that BusinessTruth does not support.",
            )
    for match in _PERCENT.finditer(text):
        if _supported(allow, match.group(1)):
            continue
        window = text[max(0, match.start() - 40) : match.end() + 40]
        if _SATISFACTION_CONTEXT.search(window):
            out.add(
                "truth.claims.satisfaction_percentage",
                TruthCategory.CLAIMS,
                B,
                page.path,
                "A satisfaction/success percentage is claimed that BusinessTruth does not support.",
            )
        else:
            out.add(
                "truth.claims.percentage",
                TruthCategory.CLAIMS,
                A,
                page.path,
                "A percentage appears that BusinessTruth does not contain.",
            )
    if _ALWAYS_OPEN.search(text) and not _ALWAYS_OPEN.search(allow.corpus):
        out.add(
            "truth.claims.always_available",
            TruthCategory.CLAIMS,
            B,
            page.path,
            "Round-the-clock availability (24/7) is claimed that BusinessTruth does not support.",
        )
    if _FAST.search(text) and not _FAST.search(allow.corpus):
        out.add(
            "truth.claims.response_time",
            TruthCategory.CLAIMS,
            A,
            page.path,
            "A response/turnaround time is stated that BusinessTruth does not contain.",
        )
    if _RANK.search(text) and not _RANK.search(allow.corpus):
        out.add(
            "truth.claims.ranking",
            TruthCategory.CLAIMS,
            B,
            page.path,
            "A ranking ('#1', 'number one') is claimed that BusinessTruth does not support.",
        )
    for term in {_norm_text(t) for t in _CERT.findall(text)}:
        if term not in allow.corpus:
            out.add(
                "truth.claims.certification_or_award",
                TruthCategory.CLAIMS,
                B,
                page.path,
                "A certification, accreditation, award or membership is claimed that BusinessTruth does not support.",
            )
    for first, second in _GUARANTEE_NUMBER.findall(text):
        if not _supported(allow, first or second):
            out.add(
                "truth.claims.guarantee_term",
                TruthCategory.CLAIMS,
                B,
                page.path,
                "A guarantee period is claimed that BusinessTruth does not support.",
            )
    if _GUARANTEE.search(text) and not _GUARANTEE.search(allow.corpus):
        out.add(
            "truth.claims.guarantee",
            TruthCategory.CLAIMS,
            A,
            page.path,
            "A guarantee is mentioned that BusinessTruth does not contain.",
        )
    if _SUPERLATIVE.search(text) and not _SUPERLATIVE.search(allow.corpus):
        out.add(
            "truth.claims.superlative",
            TruthCategory.CLAIMS,
            A,
            page.path,
            "A superlative ('best', 'leading') appears that BusinessTruth does not contain.",
        )


def _check_locations(page: _Page, allow: _Allow, out: _Findings) -> None:
    for street in _STREET.findall(page.visible):
        head = _norm_text(street)[:12]
        if not any(head in known for known in allow.addresses) and head not in allow.corpus:
            out.add(
                "truth.location.address_unsupported",
                TruthCategory.LOCATION,
                B,
                page.path,
                "A street address appears that is not in BusinessTruth.",
            )


def _check_assets(page: _Page, allow: _Allow, out: _Findings) -> None:
    urls = [img.src for img in page.images] + [u for css in page.css for u in _URL_IN_CSS.findall(css)]
    for url in urls:
        if url.lower().startswith(("http://", "https://", "//")) and url not in allow.asset_urls:
            out.add(
                "truth.assets.unknown_source",
                TruthCategory.ASSETS,
                B,
                page.path,
                "An image comes from a URL that is not one of this business's assets.",
            )
    for img in page.images:
        if not img.logo_hint:
            if allow.asset_urls.get(img.src) is False and _REAL_WORK_WORDS.search(img.alt):
                out.add(
                    "truth.assets.generated_as_real_work",
                    TruthCategory.ASSETS,
                    A,
                    page.path,
                    "A generated image is described as real work.",
                )
            continue
        if allow.logo_url is not None and img.src == allow.logo_url:
            continue
        if allow.asset_urls.get(img.src) is False:
            out.add(
                "truth.assets.generated_as_logo",
                TruthCategory.ASSETS,
                B,
                page.path,
                "A generated image is presented as the business's logo.",
            )
        else:
            out.add(
                "truth.assets.fabricated_logo",
                TruthCategory.ASSETS,
                B,
                page.path,
                "An image is presented as the business's logo but is not its real logo in BusinessTruth.",
            )


def _placeholder_only(email: str, source: str) -> bool:
    """H1: True when EVERY occurrence of `email` in this JS file is the
    literal value of a `placeholder` property/attribute — example input
    text (e.g. `placeholder:"nombre@correo.com"` in compiled JSX), never a
    contact destination the site publishes. Mirrors the HTML side, where
    `placeholder` attributes are not visible text (see _Parser). One other
    occurrence anywhere (a mailto:, a rendered string) keeps the finding."""
    in_placeholders = sum(value.count(email) for _, value in _PLACEHOLDER_VALUE.findall(source))
    return in_placeholders > 0 and in_placeholders == source.count(email)


def _check_scripts(files: dict[str, bytes], allow: _Allow, out: _Findings) -> None:
    """Generated JS can insert content after this static check runs; only
    literal contact destinations shipped in JS are detectable here."""
    for path in sorted(files):
        if not path.endswith(".js"):
            continue
        source = files[path].decode("utf-8", errors="ignore")
        for email in _EMAIL.findall(source):
            if email.lower() not in allow.emails and not _placeholder_only(email, source):
                out.add(
                    "truth.contact.email_unauthorized",
                    TruthCategory.CONTACT,
                    B,
                    path,
                    "Shipped JavaScript contains an email address that is not in BusinessTruth.",
                )
        for number in _WA.findall(source):
            if _digits(number) not in allow.whatsapp:
                out.add(
                    "truth.contact.whatsapp_unauthorized",
                    TruthCategory.CONTACT,
                    B,
                    path,
                    "Shipped JavaScript contains a WhatsApp destination that is not in BusinessTruth.",
                )


def validate_truth_contract(files: dict[str, bytes], *, business_truth: BusinessTruth) -> TruthContractResult:
    """Deterministic and local: the same files and truth always give the
    same result; no provider, no network."""
    allow = _allow(business_truth)
    out = _Findings()
    for page in _pages(files):
        _check_contact(page, allow, out)
        _check_legal(page, allow, out)
        _check_reviews(page, allow, out)
        _check_claims(page, allow, out)
        _check_locations(page, allow, out)
        _check_assets(page, allow, out)
    _check_scripts(files, allow, out)
    return TruthContractResult(findings=out.items)
