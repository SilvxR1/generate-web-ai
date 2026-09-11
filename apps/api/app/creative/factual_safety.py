"""Shared factual-safety constraint builder (P2.9) — used by every
CreativeDirectorProvider implementation (InternalCreativeDirector,
HiggsfieldCreativeDirector) so the prohibited-claims list a
CreativeDirection carries never depends on which provider explored it.
The specific categories mirror the task's own factual-safety list:
pricing, years of experience, certifications, reviews, guarantees,
addresses, opening hours, shipping, delivery times, materials, customer
counts, awards, availability, ecommerce.
"""

from app.domain.creative import CreativeBrief
from app.domain.creative.direction import CreativeDirectionConstraints

PROHIBITED_CLAIMS: tuple[str, ...] = (
    "pricing",
    "years_of_experience",
    "certifications",
    "reviews",
    "guarantees",
    "addresses",
    "opening_hours",
    "shipping",
    "delivery_times",
    "materials",
    "customer_counts",
    "awards",
    "availability",
    "ecommerce",
)


def constraints_for_brief(brief: CreativeBrief) -> CreativeDirectionConstraints:
    """Every factual claim traces directly to a CreativeBrief field —
    never invented here. `allowed_claims` is a small, safe generic
    vocabulary a creative direction may lean on without needing a
    specific number/date/certification behind it."""
    return CreativeDirectionConstraints(
        factual_claims=[
            f"business_name: {brief.business_name}",
            f"industry: {brief.industry}",
            *([f"tagline: {brief.tagline}"] if brief.tagline else []),
            *([f"description: {brief.description}"] if brief.description else []),
            *([f"target_customer: {brief.target_customer}"] if brief.target_customer else []),
            *[f"service: {service.name}" for service in brief.services],
        ],
        allowed_claims=["handmade" if "handmade" in (brief.description or "").lower() else "custom_service"],
        prohibited_claims=list(PROHIBITED_CLAIMS),
        required_content=["working_contact_path", "legal_pages"],
    )
