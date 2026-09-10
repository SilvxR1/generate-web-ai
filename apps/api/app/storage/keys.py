"""generate_storage_key — turns an arbitrary, untrusted client-supplied
filename into a safe storage key (Phase 3: 'safe filenames'). Never
reuses the original filename directly (path traversal, collisions,
non-ASCII/control characters) — only the extension survives, and only if
it looks like a real one."""

import re
import uuid
from pathlib import PurePosixPath

_SAFE_EXTENSION_PATTERN = re.compile(r"^[a-zA-Z0-9]{1,10}$")


def generate_storage_key(*, business_id: str, original_filename: str) -> str:
    suffix = PurePosixPath(original_filename).suffix.removeprefix(".")
    extension = f".{suffix.lower()}" if _SAFE_EXTENSION_PATTERN.match(suffix) else ""
    return f"{business_id}/{uuid.uuid4().hex}{extension}"
