"""app.creative.frontend_engine.visual_qa (P2 continuation Part 4,
"Visual QA V1") — real screenshots at desktop/tablet/mobile persisted
via StorageProvider, reusing app.creative.frontend_engine.browser_qa's
already-proven real-browser checks as the pass/fail verdict. Reuses
tests/test_browser_qa.py's _real_build_files (a real Astro build through
the actual generative pipeline), same pattern as e.g.
tests/test_custom_domain_api.py importing a fixture from another test
module in this suite.
"""

from app.creative.frontend_engine.visual_qa import run_visual_qa
from app.storage.provider import StorageProvider, StoredFile
from tests.test_browser_qa import _real_build_files


class _InMemoryStorage(StorageProvider):
    def __init__(self) -> None:
        self.saved: dict[str, bytes] = {}

    def save(self, *, storage_key: str, content: bytes) -> StoredFile:
        self.saved[storage_key] = content
        return StoredFile(storage_key=storage_key)

    def delete(self, storage_key: str) -> None:
        self.saved.pop(storage_key, None)

    def url_path(self, storage_key: str) -> str:
        return f"/uploads/{storage_key}"

    def load(self, storage_key: str) -> bytes:
        return self.saved[storage_key]


def test_visual_qa_persists_a_real_screenshot_per_viewport_and_passes():
    files = _real_build_files()
    storage = _InMemoryStorage()

    result = run_visual_qa(files, business_id="visual-qa-co", storage=storage)

    assert result.passed, [f for f in result.browser_qa.failures]
    assert set(result.screenshot_keys) == {"desktop", "tablet", "mobile"}
    for viewport, storage_key in result.screenshot_keys.items():
        saved_bytes = storage.saved[storage_key]
        assert saved_bytes.startswith(b"\x89PNG"), f"{viewport} screenshot is not a real PNG"


def test_visual_qa_detects_missing_primary_heading():
    files = _real_build_files()
    stripped = files["index.html"].decode().replace('<h1 id="top" class="pulse">Browser QA Test</h1>', "<p>hi</p>")
    files = {**files, "index.html": stripped.encode()}
    storage = _InMemoryStorage()

    result = run_visual_qa(files, business_id="visual-qa-co", storage=storage)

    heading_findings = [f for f in result.browser_qa.findings if f.check == "has_primary_heading"]
    assert any(not f.passed for f in heading_findings)
    assert not result.passed
    # Screenshots are still persisted even on failure — a failure must
    # always be inspectable, never just a boolean.
    assert set(result.screenshot_keys) == {"desktop", "tablet", "mobile"}
