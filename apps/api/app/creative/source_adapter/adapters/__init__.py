"""Registered source-family adapters (H2). Selection is by detection on
the SourceManifest: exactly one adapter must recognise an export, or it is
UNSUPPORTED (no_family_adapter)."""

from app.creative.source_adapter.adapters.base import ADAPTER_CONTRACT_VERSION, SourceFamilyAdapter
from app.creative.source_adapter.adapters.higgsfield_tanstack import ADAPTER as HIGGSFIELD_TANSTACK
from app.creative.source_adapter.manifest import SourceManifest

ADAPTERS: tuple[SourceFamilyAdapter, ...] = (HIGGSFIELD_TANSTACK,)


def select_adapter(manifest: SourceManifest) -> SourceFamilyAdapter | None:
    matches = [adapter for adapter in ADAPTERS if adapter.detect(manifest)]
    return matches[0] if len(matches) == 1 else None


__all__ = ["ADAPTERS", "ADAPTER_CONTRACT_VERSION", "select_adapter"]
