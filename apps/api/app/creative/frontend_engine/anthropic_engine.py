"""AnthropicFrontendEngine — the first, replaceable FrontendEngineer
implementation (app.creative.frontend_engine.engine). Orchestrates the
full generate() pipeline: build the prompt (prompts.py) -> call Claude
for a GeneratedProjectManifest (client.py) -> enforce the dependency
allowlist (dependency_policy.py) -> write it into an isolated workspace
plus engine-authored config/legal pages (workspace.py, legal_pages.py) ->
run a real npm install + astro build (build.py) -> archive the generated
*source* durably via the existing StorageProvider (never the ephemeral
/tmp workspace path — see this class's own docstring below) -> return a
FrontendEngineResult.

Never receives production secrets: this class's own constructor takes
only an already-configured `anthropic.Anthropic` client and a
StorageProvider — no database session, no tenant credentials, no
Higgsfield/n8n/Cloudflare configuration of any kind reaches it or the
prompt it builds.
"""

import logging
import tarfile
import time
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path

import anthropic

from app.config import Settings
from app.creative.frontend_engine.build import build_generative_workspace
from app.creative.frontend_engine.client import AnthropicManifestClient
from app.creative.frontend_engine.dependency_policy import validate_dependencies
from app.creative.frontend_engine.engine import FrontendEngineer, FrontendEngineResult
from app.creative.frontend_engine.legal_pages import build_legal_pages
from app.creative.frontend_engine.prompts import build_system_prompt, build_user_message
from app.creative.frontend_engine.templates import ASTRO_CONFIG, TSCONFIG, build_package_json
from app.creative.frontend_engine.workspace import allocate_workspace, cleanup_workspace, write_manifest
from app.creative.observability import StageTimer
from app.domain.business_config import BusinessConfig
from app.domain.creative import CreativeBriefAsset
from app.domain.creative.direction import CreativeDirection
from app.storage import StorageProvider, generate_storage_key

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5"


class AnthropicFrontendEngine(FrontendEngineer):
    name = "anthropic"

    def __init__(
        self, client: AnthropicManifestClient, *, storage: StorageProvider, model: str = DEFAULT_MODEL
    ) -> None:
        self._client = client
        self._storage = storage
        self._model = model

    def generate(
        self,
        *,
        business_config: BusinessConfig,
        creative_direction: CreativeDirection,
        assets: Sequence[CreativeBriefAsset],
        platform_contract_version: str,
        business_id: str,
        api_base_url: str | None = None,
    ) -> FrontendEngineResult:
        del platform_contract_version  # Not needed for generation itself — validated downstream by the caller.
        started = time.monotonic()

        with StageTimer(
            stage="frontend_generate", business_id=business_id, provider=self.name, model=self._model
        ) as timer:
            try:
                manifest = self._client.generate_manifest(
                    system=build_system_prompt(),
                    user_content=build_user_message(
                        business_config=business_config, creative_direction=creative_direction, assets=assets
                    ),
                )
                validate_dependencies(manifest.additional_dependencies)
                logger.info(
                    "frontend_engine dependencies validated (%d requested)", len(manifest.additional_dependencies)
                )
            except Exception:
                timer.mark_failure()
                raise

        workspace = allocate_workspace()
        try:
            package_json = build_package_json(
                name=business_config.business_profile.slug,
                additional_dependencies=manifest.additional_dependencies,
            )
            write_manifest(
                workspace, manifest, package_json=package_json, astro_config=ASTRO_CONFIG, tsconfig=TSCONFIG
            )
            for relative_path, content in build_legal_pages(business_config).items():
                page_path = workspace / relative_path
                page_path.parent.mkdir(parents=True, exist_ok=True)
                page_path.write_text(content, encoding="utf-8")
            logger.info("frontend_engine workspace written (%s)", workspace)

            with StageTimer(stage="generative_build", business_id=business_id, provider=self.name) as build_timer:
                try:
                    logger.info("frontend_engine astro build started")
                    artifact = build_generative_workspace(
                        workspace, business_id=business_id, api_base_url=api_base_url
                    )
                    logger.info("frontend_engine astro build completed (%d files)", len(artifact.files))
                except Exception:
                    build_timer.mark_failure()
                    raise
            workspace_key = self._archive_source(workspace, business_id=business_id)
            logger.info("frontend_engine source archived (workspace_key=%s)", workspace_key)
        finally:
            cleanup_workspace(workspace)

        duration_ms = int((time.monotonic() - started) * 1000)
        return FrontendEngineResult(
            artifact=artifact,
            workspace_key=workspace_key,
            build_command="npm install && npm run build",
            output_dir="dist",
            dependencies=[*manifest.additional_dependencies],
            generator_provider=self.name,
            generator_model=self._model,
            duration_ms=duration_ms,
            notes=manifest.notes,
        )

    def _archive_source(self, workspace: Path, *, business_id: str) -> str:
        """Persists the generated *source* (never node_modules/dist — a
        rebuildable, reviewable record, not the build output itself)
        durably via the platform's existing StorageProvider, so
        GenerativeWebsiteArtifact.workspace_key names something a human
        can actually retrieve later, not a /tmp path that's already been
        deleted by the time anyone looks."""
        buffer = BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
            for relative in ("src", "package.json", "astro.config.mjs", "tsconfig.json"):
                path = workspace / relative
                if path.exists():
                    tar.add(path, arcname=relative)
        storage_key = generate_storage_key(business_id=business_id, original_filename="generative-source.tar.gz")
        self._storage.save(storage_key=storage_key, content=buffer.getvalue())
        return storage_key


def frontend_engineer_from_settings(settings: Settings, *, storage: StorageProvider) -> AnthropicFrontendEngine:
    """No default for `anthropic_api_key` — a missing key must fail
    loudly when the engine is actually used, matching
    app.analysis.claude.engine.business_analyzer_from_settings's exact
    shape."""
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return AnthropicFrontendEngine(AnthropicManifestClient(client, model=settings.anthropic_model), storage=storage)
