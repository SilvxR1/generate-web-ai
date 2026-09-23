"""Real-bytes raster image validation for uploads (A3 F-01 remediation).

The multipart Content-Type header a client sends is fully client-
controlled and trivially spoofable — declaring `image/jpeg` on arbitrary
bytes costs an attacker nothing. This module never trusts that header for
LOGO/IMAGE asset kinds; it sniffs the real file signature and performs a
real Pillow decode (restricted to the sniffed format only, so a spoofed
header can never make Pillow pick a different, possibly riskier decoder)
before anything is written to storage.

Deliberately does NOT accept SVG (or any other vector/markup format) — see
docs/security.md's A3 section for why SVG upload support was removed
entirely rather than sanitized: an SVG is inherently an XML+script
document wearing an image extension, and this codebase has no sanitizer
and no compelling product requirement for one yet.

Same decompression-bomb bounds (`MAX_IMAGE_SIDE`/`MAX_IMAGE_PIXELS`) as
the already-established pattern in app.domain.creative.brand_intelligence
— kept as its own small copy here rather than importing that module's
private helpers, since brand intelligence and upload validation are
unrelated concerns that happen to share one safe-decode recipe.
"""

from io import BytesIO

from PIL import Image

MAX_IMAGE_SIDE = 8192
MAX_IMAGE_PIXELS = 24_000_000

# Every format app.routers.creative's _ALLOWED_UPLOAD_CONTENT_TYPES
# accepts for AssetKind.LOGO/IMAGE. The same width*height bound below
# rejects a GIF decompression bomb exactly like any other format's —
# Pillow reports .size from the header before decoding pixel data, so
# the check runs before the expensive/dangerous part either way.
_SUPPORTED_FORMATS = ("JPEG", "PNG", "WEBP", "GIF")

_CONTENT_TYPE_FOR_FORMAT = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "GIF": "image/gif",
}


class InvalidImageError(ValueError):
    """`code` is a stable machine code, never free text derived from the
    input bytes."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _sniff_format(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "GIF"
    return None


def validate_raster_image(data: bytes) -> str:
    """Raises InvalidImageError unless `data` is a real, safely-decodable
    JPEG/PNG/WebP image within safe dimension bounds. Returns the REAL
    (sniffed, decoded) content type on success — callers must use this
    return value for any allowlist/policy decision, never the caller's
    own declared Content-Type header."""
    if not data:
        raise InvalidImageError("empty_image")

    fmt = _sniff_format(data)
    if fmt is None:
        raise InvalidImageError("unsupported_or_malformed_image")

    try:
        image = Image.open(BytesIO(data), formats=[fmt])
        width, height = image.size
        if width <= 0 or height <= 0:
            raise InvalidImageError("malformed_image")
        if width > MAX_IMAGE_SIDE or height > MAX_IMAGE_SIDE or width * height > MAX_IMAGE_PIXELS:
            raise InvalidImageError("image_too_many_pixels")
        image.load()  # forces a full decode — raises on truncated/corrupt data
    except InvalidImageError:
        raise
    except Exception as exc:  # noqa: BLE001 — any Pillow/decoder failure means "not a valid image", never a 500
        raise InvalidImageError("malformed_image") from exc

    return _CONTENT_TYPE_FOR_FORMAT[fmt]
