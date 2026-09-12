"""run_visual_qa — P2 continuation Part 4, "Visual QA V1": deliberately
not an AI design-rating system (this task explicitly says not to
over-engineer it) — real screenshots at desktop/tablet/mobile, persisted
as durable QA artifacts via the existing StorageProvider, plus the
deterministic rendering-failure checks app.creative.frontend_engine.
browser_qa already performs in that same real-browser pass (blank pages,
severe overflow, invisible/zero-size main content, broken images,
missing primary heading/content). A future AI VisualCritic (comparing a
persisted screenshot against the originating CreativeDirection's intent)
is a clean, additive extension of this same boundary — it would consume
`VisualQAResult.screenshot_keys`, never replace this module — but is
explicitly not required for P2 and is not implemented here.
"""

from dataclasses import dataclass, field

from app.creative.frontend_engine.browser_qa import DEFAULT_VIEWPORTS, BrowserQAResult, run_browser_qa
from app.storage import StorageProvider, generate_storage_key


@dataclass
class VisualQAResult:
    browser_qa: BrowserQAResult
    # {viewport_name: storage_key} — real PNG evidence, retrievable via
    # StorageProvider.url_path/load, never regenerated from thin air.
    screenshot_keys: dict[str, str] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.browser_qa.passed


def run_visual_qa(files: dict[str, bytes], *, business_id: str, storage: StorageProvider) -> VisualQAResult:
    """Captures one screenshot per required viewport (desktop 1440x900,
    tablet 768x1024, mobile 390x844) and persists each durably, then
    reuses browser_qa's own deterministic checks (no_broken_images,
    no_horizontal_overflow, has_visible_content, page_loads) as this
    module's "blank page / severe overflow / invisible content / broken
    images" verdict — one real browser pass, not two."""
    browser_result = run_browser_qa(files, viewports=DEFAULT_VIEWPORTS, capture_screenshots=True)

    screenshot_keys: dict[str, str] = {}
    for viewport_name, png_bytes in browser_result.screenshots.items():
        storage_key = generate_storage_key(business_id=business_id, original_filename=f"{viewport_name}.png")
        storage.save(storage_key=storage_key, content=png_bytes)
        screenshot_keys[viewport_name] = storage_key

    return VisualQAResult(browser_qa=browser_result, screenshot_keys=screenshot_keys)
