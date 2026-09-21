"""Brand Intelligence (P2.6) — MEASURED visual facts about an authoritative
brand raster (the official logo). Provider-independent: nothing here knows
about Higgsfield, storage, tenants or prompts.

MEASURED vs INTERPRETED. This module only MEASURES: which colors a logo's
pixels actually contain and objective properties of each (relative
luminance, a light/mid/dark tone, a saturation band). It never interprets:
no personality, audience, mood, symbolism, style label or font is inferred —
"the logo has circles" says nothing about the brand, and no code path here
can say otherwise. `BrandVisualProfile.semantic_analysis` therefore stays
"not_performed".

ALGORITHM (`logo_quantization_v1`, deterministic, pure Python, no numpy):

1. DECODE inside hard limits (see the limit constants): only JPEG/PNG/WebP,
   identified by signature and decoded with Pillow restricted to that one
   format; byte size, side length and pixel count are checked from the header
   BEFORE any pixel data is decoded. Anything else fails with a stable code.
2. DOWNSCALE to at most ANALYSIS_EDGE px with nearest-neighbour sampling
   (keeps real colors instead of averaging new ones into existence).
3. TRANSPARENCY: pixels with alpha < ALPHA_CUTOFF (128) are ignored. Pixels at
   or above it are counted as opaque with their stored RGB (no compositing
   over an assumed background). A fully transparent image yields no colors.
4. FLAT-REGION FILTER: only pixels whose right and lower neighbours have almost
   the same color (max channel difference <= FLAT_TOLERANCE) are counted.
   This drops anti-aliased edges and JPEG ringing — they are transitions
   BETWEEN colors, not colors — so blends never become palette entries. If a
   raster has no flat regions at all (photograph-like), every opaque pixel is
   counted instead.
5. QUANTIZE to 16 levels per channel and keep each bin's mean color.
6. CLASSIFY each bin from its mean color:
     near_white  every channel >= 235 and channel spread <= 20 (a white / off-
                 white page or JPEG background) — never a brand color;
     neutral     HSV saturation < 0.15 or value < 0.20 (greys, near-black
                 text, where hue carries no information);
     chromatic   everything else.
7. CLUSTER bins of the same class greedily, largest first, merging any bin
   within MERGE_DISTANCE (Euclidean sRGB) of a cluster's seed. Near-duplicate
   shades of one color collapse into one entry (count-weighted mean).
8. SELECT: chromatic clusters covering >= MIN_FOREGROUND_SHARE of the
   foreground (opaque, non-near-white, flat pixels), largest first, at most
   MAX_PALETTE. If NO chromatic color qualifies (a monochrome logo) the
   qualifying neutral clusters are used instead; otherwise neutrals are
   reported as excluded. Ties are broken by hex, so ordering is deterministic.

Known limitations (deliberate, documented rather than guessed around): a solid
brand-colored background behind a logo is indistinguishable from a brand
color and is kept; a pale cream or grey brand color is classified neutral and
dropped when chromatic colors exist; measured dominance is NOT a design-system
role — the only roles are "dominant" (largest measured area) and "supporting".
"""

from enum import StrEnum
from io import BytesIO
from uuid import UUID

from PIL import Image
from pydantic import BaseModel, ConfigDict

BRAND_ANALYSIS_VERSION = "p2.6-v1"
PALETTE_METHOD = "logo_quantization_v1"

# --- Limits (untrusted-input boundary) ---------------------------------
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # matches settings.max_upload_size_bytes
MAX_IMAGE_SIDE = 8192
MAX_IMAGE_PIXELS = 24_000_000
ANALYSIS_EDGE = 256
SUPPORTED_FORMATS = ("JPEG", "PNG", "WEBP")

# --- Algorithm constants ------------------------------------------------
ALPHA_CUTOFF = 128
FLAT_TOLERANCE = 12
QUANT_SHIFT = 4
MERGE_DISTANCE = 40.0
MIN_FOREGROUND_SHARE = 0.05
MAX_PALETTE = 5
MAX_EXCLUDED = 6
MIN_EXCLUDED_SHARE = 0.005
NEAR_WHITE_MIN_CHANNEL = 235
NEAR_WHITE_MAX_SPREAD = 20
NEUTRAL_MAX_SATURATION = 0.15
NEUTRAL_MAX_VALUE = 0.20

# Stable failure codes (never free text, never bytes).
FAIL_TOO_LARGE = "image_too_large_bytes"
FAIL_TOO_MANY_PIXELS = "image_too_many_pixels"
FAIL_UNSUPPORTED = "unsupported_format"
FAIL_MALFORMED = "malformed_image"
FAIL_UNREADABLE = "asset_unreadable"
FAIL_ERROR = "extraction_error"

EXCLUDED_NEAR_WHITE = "near_white_background"
EXCLUDED_NEUTRAL = "neutral_not_a_brand_signal"
EXCLUDED_LOW_COVERAGE = "below_minimum_coverage"


class BrandMeasurementError(Exception):
    """A measurement could not be made. `code` is one of the FAIL_* codes."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class MeasurementStatus(StrEnum):
    MEASURED = "measured"
    NO_DEFENSIBLE_COLORS = "no_defensible_colors"
    FAILED = "failed"


class MeasuredColor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    hex: str
    # "dominant" (largest measured area) or "supporting" — never a design role.
    role: str
    # Fraction of the foreground (opaque, non-near-white, flat) pixels.
    foreground_share: float
    # WCAG relative luminance, 0 (black) .. 1 (white).
    luminance: float
    tone: str
    saturation_band: str


class ExcludedColor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    hex: str
    reason: str
    # Fraction of all counted (opaque, flat) pixels.
    opaque_share: float


class PaletteMeasurement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = BRAND_ANALYSIS_VERSION
    method: str = PALETTE_METHOD
    colors: tuple[MeasuredColor, ...] = ()
    excluded: tuple[ExcludedColor, ...] = ()
    transparent_share: float = 0.0
    analysed_pixels: int = 0


class BrandAssetMeasurement(BaseModel):
    """The outcome for ONE authoritative asset. Carries no image bytes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_id: UUID
    status: MeasurementStatus
    failure_code: str | None = None
    palette: PaletteMeasurement | None = None


def failed_measurement(asset_id: UUID, code: str) -> BrandAssetMeasurement:
    return BrandAssetMeasurement(asset_id=asset_id, status=MeasurementStatus.FAILED, failure_code=code)


# --- Decoding -----------------------------------------------------------


def _sniff(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    return None


def _decode(data: bytes) -> Image.Image:
    """Validated, downscaled RGBA. Raises BrandMeasurementError only."""
    if not data:
        raise BrandMeasurementError(FAIL_MALFORMED)
    if len(data) > MAX_IMAGE_BYTES:
        raise BrandMeasurementError(FAIL_TOO_LARGE)
    fmt = _sniff(data)
    if fmt is None:
        raise BrandMeasurementError(FAIL_UNSUPPORTED)
    try:
        image = Image.open(BytesIO(data), formats=[fmt])
        width, height = image.size
        if width <= 0 or height <= 0:
            raise BrandMeasurementError(FAIL_MALFORMED)
        if width > MAX_IMAGE_SIDE or height > MAX_IMAGE_SIDE or width * height > MAX_IMAGE_PIXELS:
            raise BrandMeasurementError(FAIL_TOO_MANY_PIXELS)
        if fmt == "JPEG" and image.mode in ("RGB", "L"):
            # DCT-domain downscale: decodes a fraction of the pixels.
            image.draft(image.mode, (ANALYSIS_EDGE * 2, ANALYSIS_EDGE * 2))
        image.load()
        rgba = image.convert("RGBA")
        rgba.thumbnail((ANALYSIS_EDGE, ANALYSIS_EDGE), Image.Resampling.NEAREST)
        return rgba
    except BrandMeasurementError:
        raise
    except Exception as exc:  # noqa: BLE001 — truncated/corrupt data raises many types
        raise BrandMeasurementError(FAIL_MALFORMED) from exc


# --- Color math ----------------------------------------------------------

_Rgb = tuple[int, int, int]


def _hex(rgb: _Rgb) -> str:
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def _channel_linear(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: _Rgb) -> float:
    return 0.2126 * _channel_linear(rgb[0]) + 0.7152 * _channel_linear(rgb[1]) + 0.0722 * _channel_linear(rgb[2])


def _saturation_value(rgb: _Rgb) -> tuple[float, float]:
    high, low = max(rgb), min(rgb)
    return (0.0 if high == 0 else (high - low) / high), high / 255


def _tone(luminance: float) -> str:
    if luminance < 0.18:
        return "dark"
    return "light" if luminance >= 0.5 else "mid"


def _saturation_band(saturation: float) -> str:
    if saturation < 0.35:
        return "muted"
    return "moderate" if saturation < 0.65 else "vivid"


def _classify(rgb: _Rgb) -> str:
    high, low = max(rgb), min(rgb)
    if low >= NEAR_WHITE_MIN_CHANNEL and high - low <= NEAR_WHITE_MAX_SPREAD:
        return "near_white"
    saturation, value = _saturation_value(rgb)
    if saturation < NEUTRAL_MAX_SATURATION or value < NEUTRAL_MAX_VALUE:
        return "neutral"
    return "chromatic"


def _distance(a: _Rgb, b: _Rgb) -> float:
    return float((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


class _Cluster:
    __slots__ = ("seed", "count", "_sums")

    def __init__(self, seed: _Rgb, count: int) -> None:
        self.seed = seed
        self.count = count
        self._sums = [seed[0] * count, seed[1] * count, seed[2] * count]

    def add(self, rgb: _Rgb, count: int) -> None:
        self.count += count
        for index in range(3):
            self._sums[index] += rgb[index] * count

    @property
    def mean(self) -> _Rgb:
        return (
            round(self._sums[0] / self.count),
            round(self._sums[1] / self.count),
            round(self._sums[2] / self.count),
        )


def _cluster(bins: list[tuple[int, _Rgb, int]]) -> list[_Cluster]:
    """`bins` are (count, mean rgb, key). Largest first, ties by key."""
    clusters: list[_Cluster] = []
    for count, rgb, _key in sorted(bins, key=lambda item: (-item[0], item[2])):
        for cluster in clusters:
            if _distance(rgb, cluster.seed) <= MERGE_DISTANCE:
                cluster.add(rgb, count)
                break
        else:
            clusters.append(_Cluster(rgb, count))
    return clusters


def _rank(clusters: list[_Cluster]) -> list[_Cluster]:
    return sorted(clusters, key=lambda cluster: (-cluster.count, _hex(cluster.mean)))


# --- Measurement ---------------------------------------------------------


def _flat_pixels(pixels: list[_Rgb | None], width: int, height: int) -> list[_Rgb]:
    flat: list[_Rgb] = []
    for y in range(height):
        row = y * width
        for x in range(width):
            color = pixels[row + x]
            if color is None:
                continue
            uniform = True
            for neighbour_index in (
                row + x + 1 if x + 1 < width else -1,
                row + width + x if y + 1 < height else -1,
            ):
                if neighbour_index < 0:
                    continue
                neighbour = pixels[neighbour_index]
                if neighbour is None or (
                    abs(color[0] - neighbour[0]) > FLAT_TOLERANCE
                    or abs(color[1] - neighbour[1]) > FLAT_TOLERANCE
                    or abs(color[2] - neighbour[2]) > FLAT_TOLERANCE
                ):
                    uniform = False
                    break
            if uniform:
                flat.append(color)
    return flat


def _measure(rgba: Image.Image) -> PaletteMeasurement:
    width, height = rgba.size
    raw = rgba.tobytes()
    pixels: list[_Rgb | None] = []
    transparent = 0
    for index in range(0, len(raw), 4):
        if raw[index + 3] < ALPHA_CUTOFF:
            pixels.append(None)
            transparent += 1
        else:
            pixels.append((raw[index], raw[index + 1], raw[index + 2]))
    total = width * height
    transparent_share = round(transparent / total, 4) if total else 0.0
    if transparent == total:
        return PaletteMeasurement(transparent_share=transparent_share)

    counted = _flat_pixels(pixels, width, height) or [color for color in pixels if color is not None]

    bins: dict[int, list[int]] = {}
    for red, green, blue in counted:
        key = ((red >> QUANT_SHIFT) << 8) | ((green >> QUANT_SHIFT) << 4) | (blue >> QUANT_SHIFT)
        entry = bins.get(key)
        if entry is None:
            bins[key] = [1, red, green, blue]
        else:
            entry[0] += 1
            entry[1] += red
            entry[2] += green
            entry[3] += blue

    grouped: dict[str, list[tuple[int, _Rgb, int]]] = {"near_white": [], "neutral": [], "chromatic": []}
    for key, (count, red_sum, green_sum, blue_sum) in bins.items():
        mean: _Rgb = (round(red_sum / count), round(green_sum / count), round(blue_sum / count))
        grouped[_classify(mean)].append((count, mean, key))

    near_white = _rank(_cluster(grouped["near_white"]))
    neutral = _rank(_cluster(grouped["neutral"]))
    chromatic = _rank(_cluster(grouped["chromatic"]))

    counted_total = len(counted)
    foreground = sum(c.count for c in neutral) + sum(c.count for c in chromatic)

    def qualifies(cluster: _Cluster) -> bool:
        return foreground > 0 and cluster.count / foreground >= MIN_FOREGROUND_SHARE

    chosen = [c for c in chromatic if qualifies(c)][:MAX_PALETTE]
    monochrome = not chosen
    if monochrome:
        chosen = [c for c in neutral if qualifies(c)][:MAX_PALETTE]

    colors: list[MeasuredColor] = []
    for rank, cluster in enumerate(chosen):
        mean = cluster.mean
        saturation, _ = _saturation_value(mean)
        luminance = relative_luminance(mean)
        colors.append(
            MeasuredColor(
                hex=_hex(mean),
                role="dominant" if rank == 0 else "supporting",
                foreground_share=round(cluster.count / foreground, 4),
                luminance=round(luminance, 3),
                tone=_tone(luminance),
                saturation_band=_saturation_band(saturation),
            )
        )

    chosen_ids = {id(cluster) for cluster in chosen}
    excluded: list[tuple[int, str, str]] = []  # (count, hex, reason)
    for cluster in near_white:
        excluded.append((cluster.count, _hex(cluster.mean), EXCLUDED_NEAR_WHITE))
    for cluster in neutral:
        if id(cluster) not in chosen_ids:
            reason = EXCLUDED_LOW_COVERAGE if monochrome else EXCLUDED_NEUTRAL
            excluded.append((cluster.count, _hex(cluster.mean), reason))
    for cluster in chromatic:
        if id(cluster) not in chosen_ids:
            excluded.append((cluster.count, _hex(cluster.mean), EXCLUDED_LOW_COVERAGE))
    excluded.sort(key=lambda item: (-item[0], item[1]))
    excluded_colors = tuple(
        ExcludedColor(hex=hex_value, reason=reason, opaque_share=round(count / counted_total, 4))
        for count, hex_value, reason in excluded
        if count / counted_total >= MIN_EXCLUDED_SHARE
    )[:MAX_EXCLUDED]

    return PaletteMeasurement(
        colors=tuple(colors),
        excluded=excluded_colors,
        transparent_share=transparent_share,
        analysed_pixels=counted_total,
    )


def measure_palette(image_bytes: bytes) -> PaletteMeasurement:
    """Measure the palette of one raster. Raises BrandMeasurementError."""
    return _measure(_decode(image_bytes))


def measure_asset_palette(asset_id: UUID, image_bytes: bytes) -> BrandAssetMeasurement:
    """Never raises: a failure is a value, so Brand Intelligence can never
    break a generation."""
    try:
        palette = measure_palette(image_bytes)
    except BrandMeasurementError as exc:
        return failed_measurement(asset_id, exc.code)
    except Exception:  # noqa: BLE001 — non-critical by contract
        return failed_measurement(asset_id, FAIL_ERROR)
    status = MeasurementStatus.MEASURED if palette.colors else MeasurementStatus.NO_DEFENSIBLE_COLORS
    return BrandAssetMeasurement(asset_id=asset_id, status=status, palette=palette)
