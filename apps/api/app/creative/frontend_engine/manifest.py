"""GeneratedProjectManifest — the structured-output shape a
FrontendEngineer implementation returns (app.creative.frontend_engine.engine).
Deliberately narrow: an AI Frontend Engineer submits *content files* under
`src/`/`public/` plus a list of *requested* dependency names — never a
`package.json`, `astro.config.mjs`, or `tsconfig.json` of its own (those
are always engine-authored, see workspace.py's RESERVED_PATHS/templates),
and never a raw dependency version string (app.creative.frontend_engine.
dependency_policy resolves an approved name to its one pinned version).
This is the file-manifest security boundary P2's "workspace isolation"
section asks for, expressed as a type the provider boundary itself
enforces, not just a runtime check bolted on after the fact.
"""

from pydantic import BaseModel, ConfigDict, Field


class GeneratedFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Relative to the workspace root, forward slashes, no leading slash —
    # validated for real by app.creative.frontend_engine.workspace.write_manifest,
    # which is the actual security boundary; this field's type is just a
    # str because Pydantic has no "safe relative path" primitive, not a
    # substitute for that validation.
    path: str
    content: str


class GeneratedProjectManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    files: list[GeneratedFile] = Field(default_factory=list)
    # Package *names* only, checked against
    # app.creative.frontend_engine.dependency_policy.ALLOWED_DEPENDENCIES
    # — never a version string, never installed as requested verbatim.
    additional_dependencies: list[str] = Field(default_factory=list)
    # Free-text design notes from the engine (e.g. "used a diagonal-split
    # hero because ...") — never business-fact content, purely for a
    # human/Studio reviewing the generation later.
    notes: str = ""
