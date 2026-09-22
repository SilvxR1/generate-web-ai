"""Bounded decoding and color math for Image QA (P2.7).

Image bytes are an untrusted-input boundary exactly as in P2.6, so this module
REUSES P2.6's limits and format sniffing instead of defining its own
(app.domain.creative.brand_intelligence): ≤10 MiB, ≤8192 px per side, ≤24 MP,
JPEG/PNG/WebP only, all checked from the header BEFORE any pixel is decoded.
Analysis then runs on a small area-averaged thumbnail, never on full-resolution
pixels, so cost is bounded whatever the input.

Two kinds of decode failure are kept apart on purpose:
  * a DEFECT   (malformed / truncated / not an expected image format) — the
                artifact is provably bad → the integrity check FAILS;
  * a LIMIT    (over the byte / pixel limits) — we simply cannot analyze it →
                every pixel check is NOT_PERFORMED. Our own analysis budget is
                never presented as a defect in the image.
"""

import math
from dataclasses import dataclass
from io import BytesIO

from PIL import Image

from app.domain.creative.brand_intelligence import (
    ALPHA_CUTOFF,
    FAIL_MALFORMED,
    FAIL_TOO_LARGE,
    FAIL_TOO_MANY_PIXELS,
    FAIL_UNSUPPORTED,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_PIXELS,
    MAX_IMAGE_SIDE,
    _sniff,
)

__all__ = [
    "ALPHA_CUTOFF",
    "ANALYSIS_EDGE",
    "DecodedImage",
    "ImageDecodeError",
    "Lab",
    "decode_for_qa",
    "delta_e",
    "hex_to_rgb",
    "rgb_to_hex",
    "rgb_to_lab",
]

# Longest side of the analysis thumbnail. ~160x90 for 16:9 → ~14k pixels: enough
# to see color areas and coarse structure, cheap enough for pure Python.
ANALYSIS_EDGE = 160

# Decode failures that mean "the artifact is bad" vs "we cannot analyze it".
DEFECT_CODES = frozenset({FAIL_MALFORMED, FAIL_UNSUPPORTED})
LIMIT_CODES = frozenset({FAIL_TOO_LARGE, FAIL_TOO_MANY_PIXELS})


class ImageDecodeError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code

    @property
    def is_defect(self) -> bool:
        return self.code in DEFECT_CODES


@dataclass(frozen=True)
class DecodedImage:
    """A decoded artifact: true dimensions from the header plus a small RGBA
    thumbnail (area-averaged) that every pixel check works on."""

    width: int
    height: int
    format: str
    mode: str
    byte_size: int
    thumbnail: Image.Image  # RGBA, longest side ≤ ANALYSIS_EDGE


def decode_for_qa(data: bytes) -> DecodedImage:
    """Raises ImageDecodeError only."""
    if not data:
        raise ImageDecodeError(FAIL_MALFORMED)
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageDecodeError(FAIL_TOO_LARGE)
    fmt = _sniff(data)
    if fmt is None:
        raise ImageDecodeError(FAIL_UNSUPPORTED)
    try:
        image = Image.open(BytesIO(data), formats=[fmt])
        width, height = image.size
        mode = image.mode
        if width <= 0 or height <= 0:
            raise ImageDecodeError(FAIL_MALFORMED)
        if width > MAX_IMAGE_SIDE or height > MAX_IMAGE_SIDE or width * height > MAX_IMAGE_PIXELS:
            raise ImageDecodeError(FAIL_TOO_MANY_PIXELS)
        if fmt == "JPEG" and mode in ("RGB", "L"):
            image.draft(mode, (ANALYSIS_EDGE * 2, ANALYSIS_EDGE * 2))  # DCT-domain downscale
        image.load()  # raises on truncated / corrupt data
        thumbnail = image.convert("RGBA")
        thumbnail.thumbnail((ANALYSIS_EDGE, ANALYSIS_EDGE), Image.Resampling.BOX)
    except ImageDecodeError:
        raise
    except Exception as exc:  # noqa: BLE001 — corrupt data raises many types
        raise ImageDecodeError(FAIL_MALFORMED) from exc
    return DecodedImage(
        width=width, height=height, format=fmt, mode=mode, byte_size=len(data), thumbnail=thumbnail
    )


# --- color math (sRGB -> CIELAB, D65) ---------------------------------------------

Lab = tuple[float, float, float]

_LINEAR = tuple(
    (c / 255) / 12.92 if (c / 255) <= 0.04045 else (((c / 255) + 0.055) / 1.055) ** 2.4 for c in range(256)
)
_XN, _YN, _ZN = 0.95047, 1.0, 1.08883
_EPSILON, _KAPPA = 216 / 24389, 24389 / 27


def _f(t: float) -> float:
    return t ** (1 / 3) if t > _EPSILON else (_KAPPA * t + 16) / 116


def rgb_to_lab(red: int, green: int, blue: int) -> Lab:
    r, g, b = _LINEAR[red], _LINEAR[green], _LINEAR[blue]
    x = 0.4124564 * r + 0.3575761 * g + 0.1804375 * b
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = 0.0193339 * r + 0.1191920 * g + 0.9503041 * b
    fx, fy, fz = _f(x / _XN), _f(y / _YN), _f(z / _ZN)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(a: Lab, b: Lab) -> float:
    """CIE76 color difference: plain Euclidean distance in CIELAB. Simple and
    explainable; less perceptually uniform than CIEDE2000 (see the docs)."""
    return math.dist(a, b)


def hex_to_rgb(value: str) -> tuple[int, int, int] | None:
    """`#RRGGBB` only. Other configured notations (named, oklch(), ...) return
    None: the palette check reports them as not measurable instead of guessing."""
    text = value.strip()
    if len(text) == 7 and text[0] == "#":
        try:
            return int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16)
        except ValueError:
            return None
    return None


def rgb_to_hex(red: int, green: int, blue: int) -> str:
    return f"#{red:02X}{green:02X}{blue:02X}"
