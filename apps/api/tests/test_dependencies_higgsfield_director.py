"""app.dependencies.get_optional_higgsfield_director / get_creative_director
— the exact seam PR #20 (configurable Higgsfield model registry +
FallbackCreativeDirector) and PR #21 (R2 persistent storage, private
provider references) both touched independently. Every other test in
this suite exercises one side or the other through
app.dependency_overrides, which bypasses these factory functions
entirely — so neither PR's own tests would have caught a rebase that
silently dropped one side's wiring while keeping the other's. These
tests call the real factories directly, proving both survived together:
the returned HiggsfieldApiCreativeDirector is wired to BOTH the
configured model (job_type) AND the storage provider it needs for
private R2 presigned reference URLs.
"""

import pytest

from app.config import settings
from app.creative.director_fallback import FallbackCreativeDirector
from app.creative.director_internal import InternalCreativeDirector
from app.creative.higgsfield import HiggsfieldApiCreativeDirector
from app.dependencies import get_creative_director, get_optional_higgsfield_director
from app.storage.local import LocalStorageProvider


@pytest.fixture()
def configured_higgsfield(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "higgsfield_api_key_id", "test-key-id")
    monkeypatch.setattr(settings, "higgsfield_api_key_secret", "test-key-secret")
    monkeypatch.setattr(settings, "higgsfield_cli_enabled", False)


def test_optional_higgsfield_director_is_wired_to_the_configured_model(
    configured_higgsfield, monkeypatch: pytest.MonkeyPatch, tmp_path
):
    monkeypatch.setattr(settings, "higgsfield_api_model", "higgsfield-ai/soul/reference")
    storage = LocalStorageProvider(root_dir=tmp_path)

    director = get_optional_higgsfield_director(storage)

    assert isinstance(director, HiggsfieldApiCreativeDirector)
    assert director._job_type == "higgsfield-ai/soul/reference"


def test_optional_higgsfield_director_defaults_to_nano_banana(configured_higgsfield, tmp_path):
    storage = LocalStorageProvider(root_dir=tmp_path)

    director = get_optional_higgsfield_director(storage)

    assert isinstance(director, HiggsfieldApiCreativeDirector)
    assert director._job_type == "nano-banana"


def test_optional_higgsfield_director_keeps_the_storage_provider_for_presigned_references(
    configured_higgsfield, tmp_path
):
    """The exact regression this rebase's hand-merge exists to prevent:
    PR #20's own pre-rebase get_optional_higgsfield_director built
    HiggsfieldApiCreativeDirector with no `storage` argument at all — a
    naive conflict resolution keeping that version verbatim would have
    silently reverted every reference asset to its plain (non-presigned)
    storage_url, breaking private R2 assets for Higgsfield."""
    storage = LocalStorageProvider(root_dir=tmp_path)

    director = get_optional_higgsfield_director(storage)

    assert isinstance(director, HiggsfieldApiCreativeDirector)
    assert director._storage is storage


def test_creative_director_wraps_the_fully_wired_higgsfield_director_in_fallback(
    configured_higgsfield, monkeypatch: pytest.MonkeyPatch, tmp_path
):
    monkeypatch.setattr(settings, "higgsfield_api_model", "higgsfield-ai/soul/reference")
    storage = LocalStorageProvider(root_dir=tmp_path)

    director = get_creative_director(storage)

    assert isinstance(director, FallbackCreativeDirector)
    assert isinstance(director._primary, HiggsfieldApiCreativeDirector)
    assert director._primary._job_type == "higgsfield-ai/soul/reference"
    assert director._primary._storage is storage
    assert isinstance(director._fallback, InternalCreativeDirector)


def test_creative_director_fallback_only_has_no_storage_wiring_to_lose(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """No Higgsfield credentials configured — get_optional_higgsfield_director
    returns None, and get_creative_director must still construct
    successfully with InternalCreativeDirector as both the nominal and
    actual provider (P2.14: never silently presented as Higgsfield)."""
    monkeypatch.setattr(settings, "higgsfield_api_key_id", None)
    monkeypatch.setattr(settings, "higgsfield_api_key_secret", None)
    monkeypatch.setattr(settings, "higgsfield_cli_enabled", False)
    storage = LocalStorageProvider(root_dir=tmp_path)

    director = get_creative_director(storage)

    assert isinstance(director, FallbackCreativeDirector)
    assert director._primary is None
    assert isinstance(director._fallback, InternalCreativeDirector)
