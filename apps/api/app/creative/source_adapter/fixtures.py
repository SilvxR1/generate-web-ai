"""Fictional fixture businesses for the source adapter (H1/H2).

Used only by the local adapter scripts and tests — never by a request
path. Each is limited to what an owner brief would state: no contact
data, legal identifiers, logo, reviews, ratings, counts or claims.
"""

import zipfile
from pathlib import Path

from app.domain.business_config import BusinessConfig, BusinessProfile
from app.domain.business_config.automation import AutomationConfig
from app.domain.business_config.business_profile import Location, ServiceOffering
from app.domain.business_config.lead_management import LeadManagementConfig
from app.domain.enums import BusinessVertical

FIXTURE_ZIP_DATE = (1980, 1, 1, 0, 0, 0)


def _config(
    name: str,
    slug: str,
    vertical: BusinessVertical,
    city: str,
    country: str,
    services: list[tuple[str, str, str]],
    required: list[str],
) -> BusinessConfig:
    return BusinessConfig(
        business_profile=BusinessProfile(
            name=name,
            slug=slug,
            industry=vertical,
            location=Location(city=city, country=country),
            services=[ServiceOffering(id=i, name=n, description=d) for i, n, d in services],
        ),
        lead_management=LeadManagementConfig(enabled=True, required_fields=required),
        automation=AutomationConfig(lead_capture=True),
    )


def nexo_reformas_business_config() -> BusinessConfig:
    """The fictional H1 business behind the real nexo-reformas-web.zip export."""
    return _config(
        "Nexo Reformas",
        "nexo-reformas",
        BusinessVertical.HOME_RENOVATION,
        "Valencia",
        "ES",
        [
            ("reforma-integral", "Reforma integral", "Reforma completa de vivienda."),
            ("cocina", "Cocina", "Reforma de cocinas."),
            ("bano", "Baño", "Reforma de baños."),
            ("pintura", "Pintura", "Pintura de vivienda."),
        ],
        ["name", "phone"],
    )


def lumen_physio_business_config() -> BusinessConfig:
    """The fictional business behind the SYNTHETIC lumen-physio fixture."""
    return _config(
        "Lumen Physio",
        "lumen-physio",
        BusinessVertical.CLINIC,
        "Lisbon",
        "PT",
        [
            ("sports-physiotherapy", "Sports physiotherapy", "Physiotherapy for athletes."),
            ("clinical-pilates", "Clinical pilates", "Small-group clinical pilates."),
            ("osteopathy", "Osteopathy", "Manual therapy."),
        ],
        ["name", "email"],
    )


def zip_directory(source: Path, destination: Path) -> Path:
    """A deterministic ZIP of `source` (sorted entries, fixed timestamps and
    permissions, one top-level folder) — identical bytes on every run, so a
    directory fixture has a stable snapshot SHA-256."""
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(p for p in source.rglob("*") if p.is_file()):
            relative = path.relative_to(source)
            if relative.parts[0] in ("node_modules", "dist"):
                continue
            info = zipfile.ZipInfo(f"{source.name}/{relative.as_posix()}", date_time=FIXTURE_ZIP_DATE)
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes(), compresslevel=9)
    return destination
