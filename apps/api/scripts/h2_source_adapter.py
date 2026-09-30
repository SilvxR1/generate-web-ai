"""H2: adapt a supervised exported website into a GWA static WebsiteArtifact,
LOCALLY, through the source-family adapter pipeline.

    uv run python scripts/h2_source_adapter.py --fixture nexo-reformas \
        --zip /path/nexo-reformas-web.zip --work-root /tmp/gwa-h2/nexo
    uv run python scripts/h2_source_adapter.py --fixture lumen-physio --work-root /tmp/gwa-h2/lumen
    ... --plan-only    stop after inspection, classification and the plan

The businesses are fictional fixtures (app.creative.source_adapter.fixtures).
`lumen-physio` is the SYNTHETIC second export (tests/fixtures/...); its ZIP
is built deterministically from the fixture directory. No upload, no
publish, no provider call. The runtime config points at a LOCAL Lead API
origin (default http://127.0.0.1:8765), valid only for local development.
"""

import argparse
import json
import sys
import uuid
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))  # so `uv run python scripts/...` works without a separate PYTHONPATH

from app.creative.source_adapter.fixtures import (  # noqa: E402
    lumen_physio_business_config,
    nexo_reformas_business_config,
    zip_directory,
)
from app.creative.source_adapter.pipeline import adapt_export, plan_export  # noqa: E402
from app.creative.source_adapter.plan import PlanRefusedError  # noqa: E402

LUMEN_FIXTURE = API_ROOT / "tests" / "fixtures" / "higgsfield_synthetic" / "lumen-physio"
FIXTURES = {
    "nexo-reformas": (nexo_reformas_business_config, "https://nexo-reformas.example"),
    "lumen-physio": (lumen_physio_business_config, "https://lumen-physio.example"),
}


def business_id(fixture: str) -> str:
    """Deterministic fixture id (nexo-reformas keeps its H1 id)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://gwa.local/h1/{fixture}"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fixture", choices=sorted(FIXTURES), required=True)
    parser.add_argument("--zip", type=Path, help="the export ZIP (default for lumen-physio: built from the fixture)")
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    config_factory, origin = FIXTURES[args.fixture]
    zip_path = args.zip
    if zip_path is None:
        if args.fixture != "lumen-physio":
            parser.error("--zip is required for this fixture")
        args.work_root.parent.mkdir(parents=True, exist_ok=True)
        zip_path = zip_directory(LUMEN_FIXTURE, args.work_root.parent / f"{args.work_root.name}-lumen-physio.zip")
    try:
        if args.plan_only:
            planned = plan_export(zip_path, args.work_root, config_factory(), site_origin=origin)
            print(
                json.dumps(
                    {
                        "status": planned.supportability.status,
                        "plan_sha256": planned.plan.plan_sha256,
                        **planned.plan.summary,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return
        report = adapt_export(
            zip_path,
            args.work_root,
            config_factory(),
            business_id=business_id(args.fixture),
            api_base_url=args.api_base_url,
            site_origin=origin,
        )
    except PlanRefusedError as exc:
        print(f"REFUSED: {exc}")
        sys.exit(2)
    summary = {
        k: report[k] for k in ("supportability", "plan", "build", "platform_contract", "truth_contract", "ready")
    }
    summary["artifact"] = {k: v for k, v in report["artifact"].items() if k != "external_links"}
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
