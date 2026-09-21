"""Brand Intelligence extractor (P2.6) — pure tests over synthetic images built
with Pillow. No storage, database, network or provider is involved; the
extractor MEASURES colors and must never interpret them."""

import json
from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image, ImageDraw

from app.domain.creative import brand_intelligence as bi
from app.domain.creative.brand_intelligence import (
    FAIL_ERROR,
    FAIL_MALFORMED,
    FAIL_TOO_LARGE,
    FAIL_TOO_MANY_PIXELS,
    FAIL_UNSUPPORTED,
    BrandMeasurementError,
    MeasurementStatus,
    measure_asset_palette,
    measure_palette,
)

PINK, OCHRE, PLUM = (240, 133, 122), (201, 138, 78), (120, 58, 90)


def _png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _jpeg(image: Image.Image, quality: int = 85) -> bytes:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, "JPEG", quality=quality)
    return buffer.getvalue()


def _fmt(image: Image.Image, fmt: str) -> bytes:
    buffer = BytesIO()
    image.save(buffer, fmt)
    return buffer.getvalue()


def _logo_image() -> Image.Image:
    """Three overlapping circles and a dark text-like bar on white."""
    image = Image.new("RGB", (1696, 960), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((620, 306, 834, 516), fill=PINK)
    draw.ellipse((740, 306, 955, 516), fill=OCHRE)
    draw.ellipse((860, 306, 1076, 516), fill=PLUM)
    draw.rectangle((620, 590, 1080, 630), fill=(10, 10, 10))
    return image


def _close(hex_value: str, rgb: tuple[int, int, int], tolerance: float = 14.0) -> bool:
    actual = tuple(int(hex_value[i : i + 2], 16) for i in (1, 3, 5))
    return sum((a - b) ** 2 for a, b in zip(actual, rgb, strict=True)) ** 0.5 <= tolerance


def _rects(rects: list[tuple[tuple[int, int, int, int], tuple]], size=(320, 120), mode="RGB", bg="white"):
    image = Image.new(mode, size, bg)
    draw = ImageDraw.Draw(image)
    for box, fill in rects:
        draw.rectangle(box, fill=fill)
    return image


# --- what a real logo yields ---------------------------------------------------------------------


def test_an_official_logo_yields_its_measured_brand_colors():
    palette = measure_palette(_jpeg(_logo_image()))

    hexes = [color.hex for color in palette.colors]
    assert len(hexes) == 3
    for expected in (PINK, OCHRE, PLUM):
        assert any(_close(value, expected) for value in hexes), (hexes, expected)
    assert palette.method == "logo_quantization_v1" and palette.version == bi.BRAND_ANALYSIS_VERSION


def test_a_white_jpeg_background_never_becomes_a_brand_color():
    palette = measure_palette(_jpeg(_logo_image()))

    assert not any(_close(color.hex, (255, 255, 255), 30) for color in palette.colors)
    white = [item for item in palette.excluded if item.reason == bi.EXCLUDED_NEAR_WHITE]
    assert white and white[0].opaque_share > 0.8  # it dominates the pixels but is reported, not used


def test_near_black_text_is_reported_as_excluded_neutral_when_brand_colors_exist():
    palette = measure_palette(_png(_logo_image()))

    assert not any(color.tone == "dark" and color.saturation_band == "muted" for color in palette.colors)
    assert any(item.reason == bi.EXCLUDED_NEUTRAL for item in palette.excluded)


def test_anti_aliased_edges_do_not_create_extra_palette_entries():
    big = Image.new("RGB", (1600, 1600), "white")
    ImageDraw.Draw(big).ellipse((300, 300, 1300, 1300), fill=(200, 40, 60))
    smooth = big.resize((400, 400), Image.Resampling.LANCZOS)  # soft, blended edge

    palette = measure_palette(_png(smooth))

    assert len(palette.colors) == 1 and _close(palette.colors[0].hex, (200, 40, 60), 6)


def test_a_monochrome_logo_falls_back_to_its_neutral_color_instead_of_nothing():
    image = _rects([((40, 30, 280, 90), (20, 20, 20))])

    palette = measure_palette(_png(image))

    assert [color.hex for color in palette.colors] == ["#141414"]
    assert palette.colors[0].tone == "dark"
    assert any(item.reason == bi.EXCLUDED_NEAR_WHITE for item in palette.excluded)


def test_an_all_white_image_has_no_defensible_colors():
    result = measure_asset_palette(uuid4(), _png(Image.new("RGB", (64, 64), "white")))

    assert result.status is MeasurementStatus.NO_DEFENSIBLE_COLORS
    assert result.palette is not None and result.palette.colors == ()


# --- transparency ---------------------------------------------------------------------------------


def test_fully_transparent_pixels_are_ignored():
    image = _rects([((20, 20, 100, 100), (200, 30, 30, 255))], mode="RGBA", bg=(255, 255, 255, 0))

    palette = measure_palette(_png(image))

    assert [color.hex for color in palette.colors] == ["#C81E1E"]
    assert palette.transparent_share > 0.8


def test_partially_transparent_pixels_follow_the_alpha_cutoff_rule():
    image = _rects(
        [
            ((10, 10, 90, 90), (0, 200, 0, 100)),  # alpha 100 < 128: ignored
            ((110, 10, 190, 90), (0, 0, 200, 200)),  # alpha 200 >= 128: counted with its stored RGB
        ],
        mode="RGBA",
        bg=(0, 0, 0, 0),
    )

    palette = measure_palette(_png(image))

    assert [color.hex for color in palette.colors] == ["#0000C8"]


def test_a_fully_transparent_image_yields_no_colors():
    result = measure_asset_palette(uuid4(), _png(Image.new("RGBA", (32, 32), (0, 0, 0, 0))))

    assert result.status is MeasurementStatus.NO_DEFENSIBLE_COLORS
    assert result.palette is not None and result.palette.transparent_share == 1.0


# --- consolidation, determinism and ordering -----------------------------------------------------


def test_near_duplicate_colors_are_consolidated_into_one_entry():
    image = _rects(
        [
            ((10, 10, 70, 70), (224, 48, 48)),
            ((90, 10, 150, 70), (226, 50, 50)),
            ((170, 10, 230, 70), (222, 46, 46)),
            ((250, 10, 310, 70), (30, 60, 200)),
        ]
    )

    palette = measure_palette(_png(image))

    assert len(palette.colors) == 2
    assert any(_close(color.hex, (224, 48, 48), 6) for color in palette.colors)


def test_extraction_is_deterministic():
    data = _jpeg(_logo_image())

    assert measure_palette(data) == measure_palette(data)
    assert measure_palette(data).model_dump_json() == measure_palette(data).model_dump_json()


def test_palette_is_ordered_by_measured_area_with_dominant_then_supporting():
    image = _rects([((10, 10, 190, 110), (30, 60, 200)), ((220, 20, 260, 60), (200, 30, 30))])

    palette = measure_palette(_png(image))

    assert [color.hex for color in palette.colors] == ["#1E3CC8", "#C81E1E"]
    assert [color.role for color in palette.colors] == ["dominant", "supporting"]
    assert palette.colors[0].foreground_share > palette.colors[1].foreground_share


def test_equal_areas_are_ordered_by_hex_so_ordering_is_fully_deterministic():
    image = _rects([((4, 4, 27, 27), (200, 30, 30)), ((40, 4, 63, 27), (30, 60, 200))], size=(70, 40))

    palette = measure_palette(_png(image))

    assert [color.hex for color in palette.colors] == sorted(color.hex for color in palette.colors)
    assert palette.colors[0].foreground_share == palette.colors[1].foreground_share


def test_measured_properties_are_objective_and_bounded():
    palette = measure_palette(_jpeg(_logo_image()))

    for color in palette.colors:
        assert 0.0 <= color.luminance <= 1.0
        assert color.tone in {"light", "mid", "dark"}
        assert color.saturation_band in {"muted", "moderate", "vivid"}
        assert color.role in {"dominant", "supporting"}  # never a design-system role
    assert len(palette.colors) <= bi.MAX_PALETTE and len(palette.excluded) <= bi.MAX_EXCLUDED


# --- untrusted input: every failure is a value, never an exception -------------------------------


def test_a_truncated_jpeg_fails_safely_as_malformed():
    result = measure_asset_palette(uuid4(), _jpeg(_logo_image())[:200])

    assert result.status is MeasurementStatus.FAILED and result.failure_code == FAIL_MALFORMED
    assert result.palette is None


@pytest.mark.parametrize("data", [b"", b"\xff\xd8\xff" + bytes(range(64)), b"\x89PNG\r\n\x1a\n" + b"junk"])
def test_malformed_or_empty_input_fails_safely(data: bytes):
    assert measure_asset_palette(uuid4(), data).failure_code == FAIL_MALFORMED


def test_an_unsupported_format_fails_safely():
    tiny = Image.new("RGB", (8, 8), "red")
    for data in (_fmt(tiny, "GIF"), _fmt(tiny, "BMP"), _fmt(tiny, "TIFF"), b"<svg xmlns='http://www.w3.org/2000/svg'/>"):
        assert measure_asset_palette(uuid4(), data).failure_code == FAIL_UNSUPPORTED


def test_an_oversized_file_fails_safely_before_decoding():
    data = b"\xff\xd8\xff" + bytes(bi.MAX_IMAGE_BYTES)

    assert measure_asset_palette(uuid4(), data).failure_code == FAIL_TOO_LARGE


def test_an_image_with_too_many_pixels_is_refused_from_its_header_without_decoding(monkeypatch):
    bomb = _png(Image.new("L", (5000, 5000)))  # 25 MP but a few KB on disk
    wide = _png(Image.new("L", (bi.MAX_IMAGE_SIDE + 1, 1)))

    def _never(*args, **kwargs):
        raise AssertionError("pixel data must not be decoded for an over-limit image")

    monkeypatch.setattr(Image.Image, "load", _never)

    for data in (bomb, wide):
        with pytest.raises(BrandMeasurementError) as caught:
            measure_palette(data)
        assert caught.value.code == FAIL_TOO_MANY_PIXELS


def test_an_unexpected_internal_error_is_still_only_a_failed_measurement(monkeypatch):
    monkeypatch.setattr(bi, "_measure", lambda rgba: (_ for _ in ()).throw(RuntimeError("boom")))

    result = measure_asset_palette(uuid4(), _png(_logo_image()))

    assert result.status is MeasurementStatus.FAILED and result.failure_code == FAIL_ERROR


# --- measured, never interpreted -------------------------------------------------------------------


def test_the_measurement_contains_no_semantic_interpretation_and_no_image_data():
    result = measure_asset_palette(uuid4(), _jpeg(_logo_image()))
    dumped = json.dumps(result.model_dump(mode="json")).lower()

    interpretations = ("playful", "friendly", "luxur", "child", "kid", "elegant", "minimal", "warm", "cool", "mood")
    for word in (*interpretations, "brand is"):
        assert word not in dumped
    assert set(bi.MeasuredColor.model_fields) == {
        "hex",
        "role",
        "foreground_share",
        "luminance",
        "tone",
        "saturation_band",
    }
    assert "http" not in dumped and "bytes" not in dumped
