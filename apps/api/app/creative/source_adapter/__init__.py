"""Source adapter (H1 -> H2): take ownership of a website exported by an
external builder (Higgsfield Supercomputer) and turn it into a GWA
WebsiteArtifact while preserving its design.

    snapshot -> manifest (inspection) -> classify -> plan -> apply ->
    static_build -> static_artifact -> contracts          (pipeline.py)

Generic: snapshot, manifest, tsx_scan, forms, facts, classify, plan, edits,
platform_files, cleanup, static_build, static_artifact, pipeline.
Family-specific: adapters/<family>.py (versioned adapter contract).
Export-specific, reviewed data only: overlays/<export>.py (pinned by SHA-256).
See docs/h2-higgsfield-universal-adapter.md.
"""
