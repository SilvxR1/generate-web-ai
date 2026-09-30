"""BusinessTruth discovery and claim detection (H2).

BusinessTruth > generated factual claims. The adapter does not assume
where an export writes the business's facts; it DISCOVERS them:

- text positions: string literals a visitor can read and JSX text (never
  comments, identifiers, class names, URLs or form values — tsx_scan);
- scalar facts (name, city, country) as whole words inside that text;
- services as whole text values matching a BusinessTruth service by name
  or by id (slug), so a renamed service still binds to its id;
- SERVICE COLLECTIONS: an array whose objects present >= 2 BusinessTruth
  services under one key (a services grid, a select's options). Every
  other entry of that collection is a service the export PRESENTS; one
  missing from BusinessTruth is a blocker (fail closed: nothing invented,
  nothing silently dropped), except a catch-all option ("Otro", "Other").

Each occurrence becomes a binding: the literal is replaced by the truth
value (a no-op while they are equal — recorded, never emitted as an
edit). The FACT LEDGER records which literal each fact was found as; a
later plan can be given the previous ledger, so a fact the owner changed
still binds to where the export first wrote it.

Claims (truth-independent patterns, reported by the SourceManifest) are
reconciled here: contact details BusinessTruth does not have are a
blocker (never shipped); prices, ratings, reviews, years, counts,
certifications, awards, guarantees, percentages and addresses need owner
confirmation (review). Qualitative copy is Higgsfield's editorial voice
and is not treated as a fact.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from app.creative.source_adapter import tsx_scan as ts
from app.creative.source_adapter.forms import CATCH_ALL_OPTION_VALUES, slug
from app.creative.source_adapter.plan import VirtualTree
from app.domain.business_truth import BusinessTruth

CODE_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs")
COUNTRY_NAMES = {
    "ES": {"es": "España", "en": "Spain"},
    "PT": {"es": "Portugal", "en": "Portugal"},
    "FR": {"es": "Francia", "en": "France"},
    "GB": {"es": "Reino Unido", "en": "United Kingdom"},
    "US": {"es": "Estados Unidos", "en": "United States"},
}

CLAIM_PATTERNS: dict[str, re.Pattern[str]] = {
    "price": re.compile(r"(?:\d[\d.,]*\s?(?:€|EUR\b|euros?\b|\$|USD\b|£))|(?:[€$£]\s?\d)", re.I),
    "years_experience": re.compile(
        r"\b\d+\s*(?:años|years)\s+(?:de\s+experiencia|of\s+experience|en\s+el\s+sector|in\s+business)"
        r"|\b(?:desde|since|fundad[ao]\s+en|founded\s+in)\s+(?:19|20)\d\d\b",
        re.I,
    ),
    "count": re.compile(
        r"\+\s?\d{2,}|\b\d{2,}[\d.,]*\s+(?:proyectos|clientes|reformas|obras|viviendas|pacientes|projects|clients|"
        r"customers|homes|patients|reviews|reseñas)\b",
        re.I,
    ),
    "rating": re.compile(r"\b[0-5][.,]\d\s*(?:/\s*5|estrellas|stars)\b|★", re.I),
    "review": re.compile(r"\b(?:testimonio|testimonial|reseñas?|opiniones de clientes|reviews?)\b", re.I),
    "certification": re.compile(r"\bISO\s?\d{3,5}\b|\bcertificad[oa]s?\b|\bcertified\b|\bhomologad[oa]s?\b", re.I),
    "award": re.compile(r"\b(?:premio|premiad[oa]|award(?:ed)?|galard[oó]n)\b", re.I),
    "guarantee": re.compile(r"\b(?:garant[ií]a|garantizad[oa]|guarantee[d]?|warranty)\b", re.I),
    "percentage": re.compile(r"\b\d{1,3}\s?%"),
    "contact_email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "contact_phone": re.compile(r"(?<![\w/])(?:\+\d{1,3}[\s-]?)?(?:\d[\s-]?){9,12}(?![\w/])"),
    "address": re.compile(r"\b(?:calle|c/|avda\.?|avenida|plaza|paseo|street|avenue|road)\s+[A-ZÁÉÍÓÚ]\w+", re.I),
}
_PROSE = re.compile(r"[^\W\d_]{3,}")
HARD_CLAIMS = frozenset(
    {
        "price",
        "years_experience",
        "count",
        "rating",
        "review",
        "certification",
        "award",
        "guarantee",
        "percentage",
        "address",
    }
)


@dataclass(frozen=True)
class TextSpan:
    start: int
    end: int
    kind: str  # string | jsx-text | json


def text_spans(path: str, text: str) -> list[TextSpan]:
    """The visitor-readable text positions of one file."""
    if path.endswith(".json"):
        s = ts.scan(text)
        return [
            TextSpan(t.start + 1, t.end - 1, "json")
            for t in s.strings
            if ts.string_context(s, t)[0] != "json-key" and not t.value.startswith(("http:", "https:", "/"))
        ]
    if not path.endswith(CODE_SUFFIXES):
        return []
    s = ts.scan(text)
    spans = [TextSpan(t.start + 1, t.end - 1, "string") for t in s.strings if ts.is_text_string(s, t)]
    spans += [TextSpan(a, b, "jsx-text") for a, b in ts.jsx_text_runs(s)]
    return sorted(spans, key=lambda sp: sp.start)


@dataclass(frozen=True)
class Occurrence:
    path: str
    start: int
    end: int
    kind: str


@dataclass
class FactBinding:
    field: str
    literal: str  # as found in the export
    value: str  # BusinessTruth value
    occurrences: list[Occurrence]

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "literal": self.literal,
            "value": self.value,
            "changes_text": self.literal != self.value,
            "occurrences": [{"path": o.path, "kind": o.kind} for o in self.occurrences],
        }


@dataclass
class FactDiscovery:
    bindings: list[FactBinding]
    presented_services: list[dict[str, str]]  # literal, path, key, status (truth|catch-all|unknown)
    findings: list[dict[str, str]]
    ledger: dict[str, str]


def _finding(code: str, severity: str, subject: str, detail: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "subject": subject, "detail": detail}


def _whole_word(text: str, literal: str, spans: list[TextSpan]) -> list[tuple[int, int, str]]:
    found = []
    for m in re.finditer(re.escape(literal), text):
        if ts.is_word_boundary(text, m.start(), m.end()):
            span = next((sp for sp in spans if sp.start <= m.start() and m.end() <= sp.end), None)
            if span is not None:
                found.append((m.start(), m.end(), span.kind))
    return found


def _service_collections(path: str, text: str, match: Callable[[str], str | None]) -> list[dict[str, str]]:
    """Entries of arrays that present >= 2 BusinessTruth services under one key."""
    s = ts.scan(text)
    groups: dict[tuple[int, str], int] = {}
    for token in s.strings:
        kind, key = ts.string_context(s, token)
        if kind != "key" or key is None or key in ts.NON_TEXT_KEYS or match(token.value.strip()) is None:
            continue
        obj = ts.enclosing(s, token.start, "{")
        arr = ts.enclosing(s, obj, "[") if obj is not None else None
        if arr is not None:
            groups[(arr, key)] = groups.get((arr, key), 0) + 1
    presented = []
    for (arr, key), count in sorted(groups.items()):
        if count < 2:
            continue
        for a, b in ts.array_elements(s, arr):
            element = s.text[a:b]
            m = re.search(rf"\b{re.escape(key)}\s*:\s*([\"'])(.*?)\1", element)
            if m is None:
                continue
            literal = m.group(2).strip()
            if match(literal) is not None:
                status = "truth"
            else:
                sibling = re.search(r"\bvalue\s*:\s*([\"'])(.*?)\1", element)
                catch_all = slug(literal).split("-")[0] in CATCH_ALL_OPTION_VALUES or (
                    sibling is not None and slug(sibling.group(2)) in CATCH_ALL_OPTION_VALUES
                )
                status = "catch-all" if catch_all else "unknown"
            presented.append({"literal": literal, "path": path, "key": key, "status": status})
    return presented


def discover_facts(
    tree: VirtualTree,
    paths: list[str],
    truth: BusinessTruth,
    *,
    locale: str,
    ledger: dict[str, str] | None = None,
) -> FactDiscovery:
    ledger = dict(ledger or {})
    findings: list[dict[str, str]] = []
    scalars: dict[str, str] = {"identity.name": truth.identity.name}
    if truth.location.city:
        scalars["location.city"] = truth.location.city
    country = COUNTRY_NAMES.get(truth.location.country or "", {}).get(locale)
    if country:
        scalars["location.country_name"] = country
    services = {f"services.{s.id}": s.name for s in truth.services}
    by_slug = {slug(s.id): f"services.{s.id}" for s in truth.services}
    by_slug |= {slug(s.name): f"services.{s.id}" for s in truth.services}
    by_name = {s.name: f"services.{s.id}" for s in truth.services}
    by_name |= {literal: f for f, literal in ledger.items() if f in services}

    def match_service(value: str) -> str | None:
        """By exact name (or ledger literal), else by id/name slug — but only
        for display text: a literal that already IS a slug ("cocina") is a
        machine value (an option value, an enum member), never bound."""
        if not value:
            return None
        if value in by_name:
            return by_name[value]
        return None if value == slug(value) else by_slug.get(slug(value))

    texts = {p: tree.text(p) for p in paths if tree.exists(p)}
    spans = {p: text_spans(p, t) for p, t in texts.items()}

    bindings: list[FactBinding] = []
    for field_name, value in scalars.items():
        literal = ledger.get(field_name, value)
        occurrences = [
            Occurrence(p, a, b, kind) for p in sorted(texts) for a, b, kind in _whole_word(texts[p], literal, spans[p])
        ]
        if occurrences:
            bindings.append(FactBinding(field_name, literal, value, occurrences))
            ledger[field_name] = literal
        else:
            findings.append(
                _finding(
                    "truth_fact_not_presented",
                    "info",
                    field_name,
                    f"BusinessTruth {field_name} ({value!r}) does not appear in the export's text",
                )
            )

    service_hits: dict[str, list[Occurrence]] = {}
    service_literals: dict[str, str] = {}
    for p in sorted(texts):
        for sp in spans[p]:
            raw = texts[p][sp.start : sp.end]
            literal = raw.strip()
            service_field = match_service(literal)
            if service_field is None:
                continue
            if service_literals.setdefault(service_field, literal) != literal:
                findings.append(
                    _finding(
                        "service_written_differently",
                        "review",
                        service_field,
                        f"the export writes {service_field} as both "
                        f"{service_literals[service_field]!r} and {literal!r}",
                    )
                )
                continue
            lead = len(raw) - len(raw.lstrip())
            service_hits.setdefault(service_field, []).append(
                Occurrence(p, sp.start + lead, sp.start + lead + len(literal), sp.kind)
            )
    for field_name, occurrences in sorted(service_hits.items()):
        bindings.append(FactBinding(field_name, service_literals[field_name], services[field_name], occurrences))
        ledger[field_name] = service_literals[field_name]

    presented = [
        entry
        for p in sorted(texts)
        if p.endswith(CODE_SUFFIXES)
        for entry in _service_collections(p, texts[p], match_service)
    ]
    for entry in presented:
        if entry["status"] == "unknown":
            findings.append(
                _finding(
                    "service_not_in_business_truth",
                    "blocker",
                    entry["literal"],
                    f"{entry['path']} presents the service {entry['literal']!r}, which BusinessTruth does not "
                    "list; add it to BusinessTruth or remove it from the export",
                )
            )
    for field_name, name in sorted(services.items()):
        if field_name not in service_hits:
            findings.append(
                _finding(
                    "truth_service_not_presented",
                    "info",
                    field_name,
                    f"BusinessTruth service {name!r} does not appear in the export",
                )
            )
    return FactDiscovery(bindings, presented, findings, dict(sorted(ledger.items())))


def detect_claims(path: str, text: str) -> list[dict[str, str | int]]:
    """Truth-independent factual-claim candidates in visitor-readable text."""
    claims: list[dict[str, str | int]] = []
    for sp in text_spans(path, text):
        chunk = text[sp.start : sp.end]
        if not _PROSE.search(chunk):
            continue  # a value such as "50% 50%" or "1fr 2fr", not a sentence
        for kind, pattern in CLAIM_PATTERNS.items():
            for m in pattern.finditer(chunk):
                claims.append(
                    {
                        "kind": kind,
                        "path": path,
                        "line": text.count("\n", 0, sp.start + m.start()) + 1,
                        "match": m.group(0).strip(),
                        "excerpt": " ".join(chunk[max(0, m.start() - 30) : m.end() + 30].split()),
                    }
                )
    return claims


def reconcile_claims(claims: list[dict], truth: BusinessTruth) -> list[dict[str, str]]:
    findings = []
    known_emails = {truth.contact.email.lower()} if truth.contact.email else set()
    known_phones = {re.sub(r"\D", "", truth.contact.phone)} if truth.contact.phone else set()
    for claim in claims:
        kind, match = claim["kind"], str(claim["match"])
        where = f"{claim['path']}:{claim['line']}"
        if kind == "contact_email" and match.lower() not in known_emails:
            findings.append(
                _finding(
                    "unverified_contact_claim",
                    "blocker",
                    where,
                    f"email {match!r} is not BusinessTruth's contact email",
                )
            )
        elif kind == "contact_phone" and re.sub(r"\D", "", match) not in known_phones:
            findings.append(
                _finding(
                    "unverified_contact_claim",
                    "blocker",
                    where,
                    f"phone {match!r} is not BusinessTruth's contact phone",
                )
            )
        elif kind in HARD_CLAIMS:
            findings.append(
                _finding(
                    "unverified_factual_claim",
                    "review",
                    where,
                    f"{kind}: {claim['excerpt']!r} is not in BusinessTruth; the owner must confirm or remove "
                    "it before launch",
                )
            )
    return findings
