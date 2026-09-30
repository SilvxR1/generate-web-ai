"""Reviewed export overlays (H2), selected ONLY by the snapshot's SHA-256.

An overlay is human-reviewed data for one exact export (see
adapters/base.ExportOverlay); a different export — even one byte — gets
no overlay and is adapted by its family adapter alone.
"""

from app.creative.source_adapter.adapters.base import ExportOverlay
from app.creative.source_adapter.overlays.nexo_reformas import OVERLAY as NEXO_REFORMAS

OVERLAYS: dict[str, ExportOverlay] = {overlay.snapshot_zip_sha256: overlay for overlay in (NEXO_REFORMAS,)}


def overlay_for(snapshot_zip_sha256: str) -> ExportOverlay | None:
    return OVERLAYS.get(snapshot_zip_sha256)
