"""Brand measurement service (P2.6) — reads an official logo ONLY through the
StorageProvider abstraction, is tenant/business-bound, and can never break a
generation. Uses the real LocalStorageProvider (in a tmp dir) as a spy: it
records every load and fails the test if a presigned URL is ever requested."""

import logging
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from PIL import Image, ImageDraw

from app.domain.business_config import BrandColors, BrandConfig, BusinessConfig, BusinessProfile
from app.domain.business_config.brand import BrandTypography
from app.domain.creative.brand_intelligence import (
    FAIL_MALFORMED,
    FAIL_UNREADABLE,
    FAIL_UNSUPPORTED,
    MeasurementStatus,
)
from app.domain.creative.brand_profile import PaletteStatus, build_brand_visual_profile
from app.domain.creative.brief import CreativeBrief, build_creative_brief
from app.domain.enums import (
    AssetCategory,
    AssetKind,
    AssetOrigin,
    BrandStrategy,
    BusinessVertical,
)
from app.services import brand_measurement
from app.services.brand_measurement import measure_brand_assets, with_brand_measurements
from app.storage.local import LocalStorageProvider

BUSINESS_ID = UUID("884eb764-2449-4bbe-a644-9d8d937f7a9d")
OTHER_BUSINESS_ID = UUID("11111111-2222-3333-4444-555555555555")


class SpyStorage(LocalStorageProvider):
    """The real local provider that records loads and refuses presigning."""

    def __init__(self, root: Path) -> None:
        super().__init__(root_dir=root)
        self.loads: list[str] = []

    def load(self, storage_key: str) -> bytes:
        self.loads.append(storage_key)
        return super().load(storage_key)

    def presigned_url(self, storage_key: str, *, expires_in_seconds: int) -> str | None:
        raise AssertionError("Brand Intelligence must never request a presigned URL")


@pytest.fixture()
def storage(tmp_path: Path) -> SpyStorage:
    return SpyStorage(tmp_path)


def _logo_jpeg() -> bytes:
    image = Image.new("RGB", (640, 360), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((100, 80, 260, 240), fill=(240, 133, 122))
    draw.ellipse((220, 80, 380, 240), fill=(201, 138, 78))
    draw.ellipse((340, 80, 500, 240), fill=(120, 58, 90))
    buffer = BytesIO()
    image.save(buffer, "JPEG", quality=85)
    return buffer.getvalue()


def _row(
    kind=AssetKind.LOGO,
    category=AssetCategory.LOGO,
    *,
    key: str | None = None,
    provider: str | None = "local",
    unavailable: str | None = None,
):
    return SimpleNamespace(
        id=uuid4(),
        kind=kind,
        category=category,
        origin=AssetOrigin.UPLOADED,
        storage_url="https://pub.example/asset",
        storage_provider=provider,
        storage_key=key,
        unavailable_reason=unavailable,
        alt_text=None,
    )


def _config(brand: BrandConfig | None = None) -> BusinessConfig:
    return BusinessConfig(
        business_profile=BusinessProfile(
            name="Cositas y Puntos", slug="cositas-y-puntos", industry=BusinessVertical.OTHER, description="Crochet."
        ),
        brand=brand,
    )


def _brief(rows, brand: BrandConfig | None = None, mode=BrandStrategy.PRESERVE) -> CreativeBrief:
    return build_creative_brief(business_config=_config(brand), assets=rows, brand_strategy=mode)


def _stored_logo(storage: SpyStorage, data: bytes | None = None, *, name: str = "logo.jpg", business=BUSINESS_ID):
    key = f"{business}/{name}"
    storage.save(storage_key=key, content=_logo_jpeg() if data is None else data)
    return _row(key=key)


# --- the happy path, through the storage abstraction only ------------------------------------------


def test_the_official_logo_is_measured_through_the_storage_abstraction(storage: SpyStorage):
    logo = _stored_logo(storage)

    measurements = measure_brand_assets(_brief([logo]), storage=storage, business_id=BUSINESS_ID)

    assert storage.loads == [logo.storage_key]
    assert len(measurements) == 1 and measurements[0].asset_id == logo.id
    assert measurements[0].status is MeasurementStatus.MEASURED
    assert len(measurements[0].palette.colors) == 3  # type: ignore[union-attr]


def test_only_the_official_logo_is_ever_read_never_gallery_or_product_images(storage: SpyStorage):
    logo = _stored_logo(storage)
    gallery = _row(AssetKind.IMAGE, AssetCategory.GALLERY, key=f"{BUSINESS_ID}/gallery.jpg")
    storage.save(storage_key=gallery.storage_key, content=_logo_jpeg())

    measure_brand_assets(_brief([gallery, logo]), storage=storage, business_id=BUSINESS_ID)

    assert storage.loads == [logo.storage_key]


def test_measurements_carry_no_bytes_urls_or_storage_keys(storage: SpyStorage):
    logo = _stored_logo(storage)

    brief = with_brand_measurements(_brief([logo]), storage=storage, business_id=BUSINESS_ID)

    assert brief.brand_measurements  # the measurement exists...
    for measurement in brief.brand_measurements:  # ...and holds only hex/ids/codes
        dumped = measurement.model_dump_json()
        assert logo.storage_key not in dumped and "pub.example" not in dumped and "http" not in dumped


# --- failures are values: generation must remain possible --------------------------------------------


def test_a_missing_storage_object_becomes_a_failed_measurement_and_the_profile_records_it(storage: SpyStorage):
    logo = _row(key=f"{BUSINESS_ID}/gone.jpg")  # never saved

    brief = with_brand_measurements(_brief([logo]), storage=storage, business_id=BUSINESS_ID)
    profile = build_brand_visual_profile(brief, brief.available_assets)

    assert brief.brand_measurements[0].failure_code == FAIL_UNREADABLE
    assert profile.palette == [] and profile.palette_status is PaletteStatus.FAILED
    assert profile.analysis_failure == FAIL_UNREADABLE and profile.has_official_logo is True


def test_a_logo_without_a_storage_key_is_never_fetched_from_its_url(storage: SpyStorage):
    logo = _row(key=None, provider=None)  # externally-hosted / legacy row

    measurements = measure_brand_assets(_brief([logo]), storage=storage, business_id=BUSINESS_ID)

    assert measurements[0].failure_code == FAIL_UNREADABLE
    assert storage.loads == []  # and no HTTP fetch exists in this service at all


def test_an_asset_from_a_different_storage_provider_is_not_read(storage: SpyStorage):
    logo = _row(key=f"{BUSINESS_ID}/logo.jpg", provider="r2")  # this server currently uses local

    measurements = measure_brand_assets(_brief([logo]), storage=storage, business_id=BUSINESS_ID)

    assert measurements[0].failure_code == FAIL_UNREADABLE and storage.loads == []


@pytest.mark.parametrize(
    "key",
    [
        f"{OTHER_BUSINESS_ID}/logo.jpg",  # another business's object
        f"{BUSINESS_ID}/../{OTHER_BUSINESS_ID}/logo.jpg",  # traversal into another business
        f"{BUSINESS_ID}//logo.jpg",
        "logo.jpg",
        f"{BUSINESS_ID}\\logo.jpg",
    ],
)
def test_tenant_isolation_a_key_outside_this_business_is_refused_before_any_read(storage: SpyStorage, key: str):
    storage.save(storage_key=f"{OTHER_BUSINESS_ID}/logo.jpg", content=_logo_jpeg())
    logo = _row(key=key)

    measurements = measure_brand_assets(_brief([logo]), storage=storage, business_id=BUSINESS_ID)

    assert measurements[0].failure_code == FAIL_UNREADABLE and storage.loads == []


def test_a_malformed_stored_image_fails_safely(storage: SpyStorage):
    logo = _stored_logo(storage, b"\xff\xd8\xff" + bytes(range(50)))

    assert measure_brand_assets(_brief([logo]), storage=storage, business_id=BUSINESS_ID)[0].failure_code == (
        FAIL_MALFORMED
    )


def test_an_unsupported_stored_format_fails_safely(storage: SpyStorage):
    buffer = BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, "GIF")
    logo = _stored_logo(storage, buffer.getvalue(), name="logo.gif")

    assert measure_brand_assets(_brief([logo]), storage=storage, business_id=BUSINESS_ID)[0].failure_code == (
        FAIL_UNSUPPORTED
    )


def test_a_storage_error_never_propagates(storage: SpyStorage, monkeypatch: pytest.MonkeyPatch):
    logo = _stored_logo(storage)
    monkeypatch.setattr(SpyStorage, "load", lambda self, key: (_ for _ in ()).throw(RuntimeError("r2 down")))

    measurements = measure_brand_assets(_brief([logo]), storage=storage, business_id=BUSINESS_ID)

    assert measurements[0].failure_code == FAIL_UNREADABLE


def test_an_unexpected_failure_in_the_service_returns_the_brief_unchanged(
    storage: SpyStorage, monkeypatch: pytest.MonkeyPatch
):
    brief = _brief([_stored_logo(storage)])
    monkeypatch.setattr(brand_measurement, "measure_brand_assets", lambda *a, **k: 1 / 0)

    result = with_brand_measurements(brief, storage=storage, business_id=BUSINESS_ID)

    assert result is brief and result.brand_measurements == []  # exactly P2.5 behavior


def test_a_missing_logo_or_an_unavailable_logo_measures_nothing(storage: SpyStorage):
    no_logo = _brief([])
    unavailable = _brief([_row(key=f"{BUSINESS_ID}/x.jpg", unavailable="Asset unavailable — please re-upload.")])

    for brief in (no_logo, unavailable):
        assert measure_brand_assets(brief, storage=storage, business_id=BUSINESS_ID) == []
        profile = build_brand_visual_profile(brief, brief.available_assets)
        assert profile.palette == [] and profile.palette_status is PaletteStatus.UNAVAILABLE
    assert storage.loads == []


# --- when a measurement can matter -------------------------------------------------------------------


def test_explicit_brand_colors_mean_no_logo_bytes_are_read(storage: SpyStorage):
    brand = BrandConfig(
        colors=BrandColors(
            primary="#E8735A", secondary="#C9A24A", accent="#7A1F3D", background="#FFFFFF", foreground="#111111"
        ),
        typography=BrandTypography(sans="Inter"),
    )

    assert measure_brand_assets(_brief([_stored_logo(storage)], brand), storage=storage, business_id=BUSINESS_ID) == []
    assert storage.loads == []


def test_a_new_direction_is_not_constrained_by_the_logo_so_it_is_not_read(storage: SpyStorage):
    brief = _brief([_stored_logo(storage)], mode=BrandStrategy.NEW_DIRECTION)

    assert measure_brand_assets(brief, storage=storage, business_id=BUSINESS_ID) == []
    assert storage.loads == []


def test_failures_are_logged_as_a_code_only(storage: SpyStorage, caplog: pytest.LogCaptureFixture):
    logo = _row(key=f"{BUSINESS_ID}/gone.jpg")

    with caplog.at_level(logging.WARNING, logger="app.services.brand_measurement"):
        measure_brand_assets(_brief([logo]), storage=storage, business_id=BUSINESS_ID)

    assert any(FAIL_UNREADABLE in record.getMessage() for record in caplog.records)
    assert not any("gone.jpg" in record.getMessage() for record in caplog.records)
