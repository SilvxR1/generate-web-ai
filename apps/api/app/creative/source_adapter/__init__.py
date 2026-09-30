"""Source adapter (H1): take ownership of a website exported by an external
builder (Higgsfield Supercomputer) and turn it into a GWA WebsiteArtifact
while preserving its design.

    snapshot (SourceInventory) -> cleanup (PortabilityCleanup) ->
    mapping (BusinessTruth binding + platform integration) -> static_build ->
    static_artifact -> contracts (pipeline)

Reusable: records, snapshot, cleanup, static_build, static_artifact, pipeline.
Source-specific: mappings/<export>.py (fixed patches/bindings/new files).
"""
