"""C3 — the C2.1 Spanish legal rules for sites built from a supervised source import.

1. Publication: an imported Spanish site with pending owner facts (or a form
   that can't collect the consent the business requires) is never
   published. The rule and the missing-fact ids are C2.1's own
   (`spanish_legal_pending_facts`); locale and forms come from the import's
   stored plan summary, and an import that doesn't record its locale is
   refused rather than assumed English. Preview, approval and rollback are
   unchanged.
2. Wording: imported Spanish legal pages name the holder as "Titular" (never
   "Razón social", never the trading name), show "Datos registrales" only
   when the owner supplied them, and state the retention period and the
   legal basis like the generator's legal-es.ts.

The route-level check (a real imported draft) is in test_r5_source_imports.py.
"""

import pytest

from app.creative.frontend_engine.legal_pages import legal_page_content
from app.domain.business_config import BusinessConfig
from app.domain.business_truth import derive_business_truth
from app.errors import AppError
from app.publishing.legal_readiness import (
    SPANISH_LEGAL_FACTS,
    require_legal_facts_for_imported_publication,
    spanish_legal_pending_facts,
)

FULL_LEGAL = {
    "legal_name": "Ana Prueba Ficticia",
    "tax_id": "00000000T",
    "address": {"street_address": "Calle Falsa 1", "postal_code": "46000", "locality": "Valencia", "country": "ES"},
    "data_retention": "12 meses desde la última comunicación",
}


def _config(*, legal: dict | None = None, consent_required: bool = False) -> dict:
    return {
        "schema_version": 1,
        "business_profile": {
            "name": "Taller Ficticio",
            "slug": "taller-ficticio",
            "industry": "other",
            "contact": {"email": "hola@taller-ficticio.example"},
        },
        "lead_management": {"enabled": True, "sources": ["website_form"], "consent_required": consent_required},
        **({"legal_profile": legal} if legal is not None else {}),
    }


def _form(*roles: str) -> dict:
    return {
        "form_id": "contact",
        "module": "src/routes/index.tsx",
        "fields": [
            {"name": role, "role": role, "key": role, "label": role, "required": True, "element": "input"}
            for role in roles
        ],
        "findings": [],
    }


def _inspection(locale: str | None = "es", forms: list[dict] | None = None) -> dict:
    site = {"origin": "https://taller-ficticio.example", **({"locale": locale} if locale else {})}
    return {"site": site, "forms": [_form("name", "email", "message", "consent")] if forms is None else forms}


def _gate(session, business, inspection: dict) -> None:
    require_legal_facts_for_imported_publication(
        session=session, tenant_id=business.tenant_id, business_id=business.id, inspection=inspection
    )


# --- 1. Publication gate --------------------------------------------------------------------------


def test_an_imported_spanish_site_with_pending_facts_is_refused(session, business):
    business.config = _config()
    session.flush()
    with pytest.raises(AppError) as error:
        _gate(session, business, _inspection())
    assert error.value.code == "legal_facts_incomplete"
    assert error.value.status_code == 409
    for fact, label in SPANISH_LEGAL_FACTS.items():  # the same facts, named the same way, as C2.1
        assert (label in str(error.value)) is (fact != "contact_email")  # the business has a contact email


def test_a_missing_tax_id_alone_still_blocks(session, business):
    business.config = _config(legal={k: v for k, v in FULL_LEGAL.items() if k != "tax_id"}, consent_required=True)
    session.flush()
    with pytest.raises(AppError) as error:
        _gate(session, business, _inspection())
    assert error.value.code == "legal_facts_incomplete"
    assert SPANISH_LEGAL_FACTS["tax_id"] in str(error.value)
    assert SPANISH_LEGAL_FACTS["legal_name"] not in str(error.value)


def test_a_missing_retention_period_blocks_a_site_with_a_form(session, business):
    business.config = _config(
        legal={k: v for k, v in FULL_LEGAL.items() if k != "data_retention"}, consent_required=True
    )
    session.flush()
    with pytest.raises(AppError) as error:
        _gate(session, business, _inspection())
    assert SPANISH_LEGAL_FACTS["data_retention"] in str(error.value)


def test_complete_facts_with_a_consent_field_are_allowed(session, business):
    business.config = _config(legal=FULL_LEGAL, consent_required=True)
    session.flush()
    _gate(session, business, _inspection())


def test_a_form_without_a_consent_field_is_refused_when_consent_is_required(session, business):
    business.config = _config(legal=FULL_LEGAL, consent_required=True)
    session.flush()
    with pytest.raises(AppError) as error:
        _gate(session, business, _inspection(forms=[_form("name", "email", "message")]))
    assert error.value.code == "legal_facts_incomplete"
    assert "consent" in str(error.value)


def test_without_a_form_only_the_identity_facts_are_required(session, business):
    legal = {k: v for k, v in FULL_LEGAL.items() if k != "data_retention"}
    business.config = _config(legal=legal)  # no retention, no consent: not needed without a form
    session.flush()
    _gate(session, business, _inspection(forms=[]))
    config = BusinessConfig.model_validate(business.config)
    assert spanish_legal_pending_facts(config, has_contact_form=False) == []


def test_an_english_import_is_outside_the_spanish_rule(session, business):
    business.config = _config()
    session.flush()
    _gate(session, business, _inspection(locale="en"))


def test_an_import_that_does_not_record_its_locale_is_refused_not_assumed(session, business):
    business.config = _config(legal=FULL_LEGAL, consent_required=True)
    session.flush()
    for inspection in (_inspection(locale=None), {}, {"site": None, "forms": []}):
        with pytest.raises(AppError) as error:
            _gate(session, business, inspection)
        assert error.value.code == "legal_facts_unverifiable"
        assert error.value.status_code == 409


# --- 2. Imported Spanish legal wording ------------------------------------------------------------


def _pages(legal: dict | None, *, consent_required: bool = True) -> dict[str, list[str]]:
    config = BusinessConfig.model_validate(_config(legal=legal, consent_required=consent_required))
    pages = legal_page_content(derive_business_truth(business_config=config), locale="es")
    return {slug: paragraphs for slug, (_title, paragraphs) in pages.items()}


def test_the_holder_is_titular_never_razon_social_nor_the_trading_name():
    pages = _pages(FULL_LEGAL)
    text = " ".join(pages["privacy"] + pages["terms"])
    assert "Razón social" not in text
    assert "Titular: Ana Prueba Ficticia." in pages["terms"]
    assert "Titular: Ana Prueba Ficticia." in pages["privacy"]
    assert not any(p.startswith("Titular") and "Taller Ficticio" in p for p in pages["terms"] + pages["privacy"])


def test_registration_details_appear_only_when_supplied():
    without = " ".join(sum(_pages(FULL_LEGAL).values(), []))
    assert "Datos registrales" not in without
    with_registry = _pages({**FULL_LEGAL, "registration_number": "Registro Mercantil de Valencia, T 1, F 1, H V-1"})
    assert "Datos registrales: Registro Mercantil de Valencia, T 1, F 1, H V-1." in with_registry["terms"]


def test_retention_and_legal_basis_are_stated_when_provided():
    privacy = _pages(FULL_LEGAL)["privacy"]
    assert "Plazo de conservación: 12 meses desde la última comunicación." in privacy
    assert any(p.startswith("Base jurídica: tu consentimiento") for p in privacy)


def test_missing_facts_are_shown_as_not_provided_and_never_invented():
    pages = _pages(None, consent_required=False)
    privacy, terms = pages["privacy"], pages["terms"]
    assert "Titular: no facilitado." in terms
    assert "NIF: no facilitado." in terms
    assert "Domicilio: no facilitado." in terms
    assert "Plazo de conservación: no facilitado." in privacy
    assert "Base jurídica: no facilitado." in privacy
    assert "Datos registrales" not in " ".join(privacy + terms)


def test_business_truth_carries_the_retention_period_and_the_consent_requirement():
    config = BusinessConfig.model_validate(_config(legal=FULL_LEGAL, consent_required=True))
    legal = derive_business_truth(business_config=config).legal
    assert legal.data_retention == "12 meses desde la última comunicación"
    assert legal.consent_required is True
    bare = derive_business_truth(business_config=BusinessConfig.model_validate(_config())).legal
    assert bare.data_retention is None and bare.consent_required is False
