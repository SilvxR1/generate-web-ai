"""Form discovery and FormMapping (H2).

Discovery (static, truth-independent — part of the SourceManifest): every
`<form>` in a module, its fields (name, element, type, required, label,
options), how it submits (the transport) and whether it already carries
anti-spam fields. Nothing is executed; the JSX is read with tsx_scan.

Mapping (plan time): each field gets a ROLE in the GWA lead model —

    name | email | phone | message | service | consent | detail

recognised from the field's own semantics (input type, autocomplete,
name, label), in any order and with any names; never from one export's
field names. Every field that is not one of the core roles is kept as a
labelled `detail` (the H1.2 Lead API extension), so nothing the visitor
typed is dropped. What cannot be mapped safely is a finding, never a
guess:

- a form with no email or phone field cannot create a lead (blocker);
- a submission transport that is not a recognised shape (blocker);
- dynamic field names, or two fields claiming one core role (review);
- a REQUIRED field with no recognised role is kept as a detail but must
  be confirmed by a human (review) — its meaning is unknown.
"""

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

from app.creative.source_adapter import tsx_scan as ts

FIELD_TAGS = ("input", "select", "textarea")
HONEYPOT_NAMES = frozenset({"hp_field", "company_website", "_gotcha", "honeypot", "bot-field"})
_NON_DATA_TYPES = frozenset({"submit", "button", "reset", "image", "hidden", "file"})
CORE_ROLES = ("name", "email", "phone", "message", "service", "consent")
MAX_DETAILS = 12  # app.schemas.public.MAX_LEAD_DETAILS

# Semantic hints (lowercase, accents stripped). Multilingual on purpose:
# exports are generated in the owner's language.
_ROLE_HINTS: dict[str, tuple[str, ...]] = {
    "email": ("email", "e-mail", "mail", "correo"),
    "phone": ("phone", "tel", "telefono", "movil", "mobile", "celular", "whatsapp"),
    "name": ("name", "fullname", "full_name", "nombre", "your-name", "yourname", "nom"),
    "message": (
        "message",
        "mensaje",
        "notes",
        "notas",
        "comments",
        "comentarios",
        "details",
        "detalles",
        "description",
        "descripcion",
        "consulta",
        "enquiry",
        "inquiry",
    ),
    "service": (
        "service",
        "servicio",
        "scope",
        "treatment",
        "tratamiento",
        "project_type",
        "projecttype",
        "tipo",
        "type_of",
    ),
    "consent": ("consent", "privacy", "privacidad", "acepto", "accept", "gdpr", "rgpd", "terms"),
}
CATCH_ALL_OPTION_VALUES = frozenset({"otro", "otra", "otros", "other", "others", "else", "altro"})


def normalize(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower().strip()


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalize(value)).strip("-")


@dataclass(frozen=True)
class FormOption:
    value: str
    label: str


@dataclass(frozen=True)
class FormField:
    name: str | None  # None = dynamic (name={...})
    element: str  # input | select | textarea
    input_type: str | None
    required: bool
    autocomplete: str | None
    label: str | None
    options: tuple[FormOption, ...] = ()
    options_dynamic: bool = False


@dataclass(frozen=True)
class FormTransport:
    kind: str  # server-function | fetch | form-action | none
    symbol: str | None = None  # the imported function the handler calls
    import_spec: str | None = None
    call_shape: str | None = None  # "data-object" = fn({ data: payload })
    result_used: bool = False  # the UI reads the transport's return value


@dataclass(frozen=True)
class FormInfo:
    form_id: str  # "<module path>#<index>"
    module: str
    index: int
    fields: tuple[FormField, ...]
    transport: FormTransport
    has_submit_handler: bool
    honeypot_present: bool
    already_wired: bool  # carries data-gwa-lead-form (adapted before)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _label_for(s: ts.Scan, span: tuple[int, int], name: str, element_id: str | None, tag: ts.JsxTag) -> str | None:
    """A field's label: a wrapper component carrying `label="X" name="<name>"`,
    a <label htmlFor=id>, or aria-label."""
    for component in sorted(set(re.findall(r"<([A-Z][\w.]*)\b", s.masked[span[0] : span[1]]))):
        for candidate in ts.jsx_open_tags(s, component):
            if span[0] <= candidate.start < span[1] and ts.jsx_attr(candidate, "name") == name:
                label = ts.jsx_attr(candidate, "label")
                if label:
                    return label.strip()
    if element_id:
        for label_tag in ts.jsx_open_tags(s, "label"):
            if span[0] <= label_tag.start < span[1] and ts.jsx_attr(label_tag, "htmlFor") == element_id:
                close, _ = ts.jsx_close_tag(s, label_tag)
                text = " ".join(re.sub(r"\{[^}]*\}|<[^>]*>", " ", s.text[label_tag.end : close]).split())
                if text:
                    return text
    aria = ts.jsx_attr(tag, "aria-label")
    return aria.strip() if aria else None


def _options(s: ts.Scan, tag: ts.JsxTag) -> tuple[tuple[FormOption, ...], bool]:
    close, _ = ts.jsx_close_tag(s, tag)
    options = []
    for option in ts.jsx_open_tags(s, "option"):
        if not tag.end <= option.start < close:
            continue
        value = ts.jsx_attr(option, "value")
        if value is None or option.self_closing:
            return (), True
        end, _ = ts.jsx_close_tag(s, option)
        label = " ".join(s.text[option.end : end].split())
        if "{" in label:
            return (), True
        options.append(FormOption(value, label))
    dynamic = "{" in s.masked[tag.end : close] and not options
    return tuple(options), dynamic


def _transport(s: ts.Scan, module_imports: list[ts.ImportDecl], server_fn_specs: set[str]) -> FormTransport:
    for decl in module_imports:
        if decl.spec not in server_fn_specs:
            continue
        for symbol in ts.imported_names(decl.clause):
            call = re.search(rf"\b{re.escape(symbol)}\s*\(\s*\{{\s*data\s*:", s.masked)
            if call is None:
                continue
            assigned = re.search(rf"(?:const|let|var)\s+(\w+)\s*=\s*await\s+{re.escape(symbol)}\s*\(", s.masked)
            used = bool(assigned and re.search(rf"\b{assigned.group(1)}\s*\.", s.masked[assigned.end() :]))
            return FormTransport("server-function", symbol, decl.spec, "data-object", used)
        return FormTransport("server-function", None, decl.spec, None, False)
    if re.search(r"\bfetch\s*\(", s.masked):
        return FormTransport("fetch")
    return FormTransport("none")


def discover_forms(module: str, text: str, server_fn_specs: set[str]) -> list[FormInfo]:
    """Every <form> in one module. `server_fn_specs` = the import specifiers
    (as written in this module) that resolve to server-function modules."""
    s = ts.scan(text)
    module_imports = ts.imports(s)
    forms = []
    for index, form_tag in enumerate(ts.jsx_open_tags(s, "form")):
        close, _ = ts.jsx_close_tag(s, form_tag)
        span = (form_tag.end, close)
        found: list[tuple[int, FormField]] = []
        honeypot = False
        for element in FIELD_TAGS:
            for tag in ts.jsx_open_tags(s, element):
                if not span[0] <= tag.start < span[1]:
                    continue
                input_type = ts.jsx_attr(tag, "type") if element == "input" else None
                if input_type in _NON_DATA_TYPES:
                    continue
                name = ts.jsx_attr(tag, "name")
                if name in HONEYPOT_NAMES or re.search(r"name\s*=\s*\{\s*HONEYPOT", tag.attrs):
                    honeypot = True
                    continue
                options, dynamic = _options(s, tag) if element == "select" else ((), False)
                label = _label_for(s, span, name, ts.jsx_attr(tag, "id"), tag) if name else None
                found.append(
                    (
                        tag.start,
                        FormField(
                            name,
                            element,
                            input_type,
                            ts.jsx_has_attr(tag, "required"),
                            ts.jsx_attr(tag, "autoComplete"),
                            label,
                            options,
                            dynamic,
                        ),
                    )
                )
        action = ts.jsx_attr(form_tag, "action")
        transport = (
            FormTransport("form-action", import_spec=action)
            if action and action.startswith(("http:", "https:", "//"))
            else _transport(s, module_imports, server_fn_specs)
        )
        forms.append(
            FormInfo(
                form_id=f"{module}#{index}",
                module=module,
                index=index,
                fields=tuple(f for _, f in sorted(found, key=lambda item: item[0])),
                transport=transport,
                has_submit_handler=ts.jsx_has_attr(form_tag, "onSubmit"),
                honeypot_present=honeypot,
                already_wired=ts.jsx_has_attr(form_tag, "data-gwa-lead-form"),
            )
        )
    return forms


# --- Mapping ---------------------------------------------------------------------


@dataclass(frozen=True)
class FieldMapping:
    name: str
    role: str  # name | email | phone | message | service | consent | detail
    key: str  # the Lead API `details[].key` (service/detail roles)
    label: str
    required: bool
    element: str


@dataclass
class FormMapping:
    form_id: str
    module: str
    fields: list[FieldMapping]
    findings: list[dict[str, str]] = field(default_factory=list)

    def role(self, role: str) -> FieldMapping | None:
        return next((f for f in self.fields if f.role == role), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "form_id": self.form_id,
            "module": self.module,
            "fields": [asdict(f) for f in self.fields],
            "findings": self.findings,
        }


def detail_key(name: str) -> str:
    key = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name)
    key = re.sub(r"[^a-z0-9_]+", "_", normalize(key)).strip("_")
    if not key or not key[0].isalpha():
        key = f"field_{key}".strip("_")
    return key[:40]


def _matches(text: str | None, hints: tuple[str, ...]) -> bool:
    if not text:
        return False
    value = normalize(re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", text))
    tokens = set(re.split(r"[^a-z0-9]+", value))
    return any(h in tokens or value.replace("-", "_") == h for h in hints)


def _role(f: FormField, service_slugs: set[str]) -> str:
    kind = (f.input_type or "").lower()
    auto = (f.autocomplete or "").lower()
    if kind == "email" or auto == "email" or _matches(f.name, _ROLE_HINTS["email"]):
        return "email"
    if kind == "tel" or auto.startswith("tel") or _matches(f.name, _ROLE_HINTS["phone"]):
        return "phone"
    if kind == "checkbox":
        return "consent" if _matches(f.name, _ROLE_HINTS["consent"]) else "detail"
    if auto in ("name", "given-name") or _matches(f.name, _ROLE_HINTS["name"]):
        return "name"
    if f.element == "select" or kind == "radio":
        option_slugs = {slug(o.value) for o in f.options} | {slug(o.label) for o in f.options}
        if option_slugs & service_slugs or _matches(f.name, _ROLE_HINTS["service"]):
            return "service"
        return "detail"
    if f.element == "textarea" or _matches(f.name, _ROLE_HINTS["message"]):
        return "message"
    return "detail"


def map_form(form: FormInfo, service_ids: set[str]) -> FormMapping:
    """Roles for every field of `form`; findings for what needs a human."""
    findings: list[dict[str, str]] = []

    def finding(code: str, severity: str, detail: str) -> None:
        findings.append({"code": code, "severity": severity, "subject": form.form_id, "detail": detail})

    service_slugs = {slug(i) for i in service_ids}
    mapped: list[FieldMapping] = []
    taken: dict[str, str] = {}
    for f in form.fields:
        if f.name is None:
            finding(
                "form_field_dynamic_name",
                "review",
                f"a <{f.element}> has a computed name; its data cannot be mapped statically",
            )
            continue
        role = _role(f, service_slugs)
        if role in CORE_ROLES and role in taken:
            finding(
                "form_role_ambiguous",
                "review",
                f"fields {taken[role]!r} and {f.name!r} both look like the {role}; the second is kept as a detail",
            )
            role = "detail"
        if role != "detail":
            taken[role] = f.name
        label = f.label or f.name
        if role == "detail" and f.required:
            finding(
                "form_required_field_unrecognized",
                "review",
                f"required field {f.name!r} ({label!r}) has no recognised lead role; it is kept as a labelled "
                "detail — a human must confirm its meaning",
            )
        key = "service" if role == "service" else detail_key(f.name)
        mapped.append(FieldMapping(f.name, role, key, label, f.required, f.element))
    if "email" not in taken and "phone" not in taken:
        finding(
            "form_without_contact_field",
            "blocker",
            "no email or phone field: the GWA Lead API cannot create a lead from this form",
        )
    keys = [m.key for m in mapped if m.role in ("service", "detail")]
    if len(keys) != len(set(keys)):
        finding("form_detail_keys_collide", "blocker", f"two fields map to the same detail key: {sorted(keys)}")
    if len(keys) > MAX_DETAILS:
        finding("form_too_many_details", "blocker", f"more than {MAX_DETAILS} additional fields (Lead API limit)")
    if form.transport.kind != "server-function" or form.transport.call_shape != "data-object":
        finding(
            "form_transport_unmappable",
            "blocker",
            f"submission transport {form.transport.kind!r} is not a recognised shape; it cannot be rewired to the "
            "GWA Lead API without a human decision",
        )
    return FormMapping(form.form_id, form.module, mapped, findings)
