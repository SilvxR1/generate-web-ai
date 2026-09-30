"""H1 proof of concept: adapt the real Higgsfield Supercomputer export
(nexo-reformas-web.zip) into a GWA static WebsiteArtifact, LOCALLY.

    uv run python scripts/h1_higgsfield_adapter.py --zip /path/nexo-reformas-web.zip --work-root /tmp/gwa-h1/run

No upload, no publish, no provider call. The business is the fictional H1
fixture (app.creative.source_adapter.mappings.nexo_reformas). The runtime
config points at a LOCAL Lead API origin (default http://127.0.0.1:8765),
which is valid only for local development (app.publishing.public_origin).
"""

import argparse
import json
import sys
import uuid
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))  # so `uv run python scripts/...` works without a separate PYTHONPATH

from app.creative.source_adapter.mappings.nexo_reformas import MAPPING, h1_fixture_business_config  # noqa: E402
from app.creative.source_adapter.pipeline import adapt_export  # noqa: E402

# Deterministic fixture id: the same business id on every run.
H1_BUSINESS_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "https://gwa.local/h1/nexo-reformas"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--site-origin", default="https://nexo-reformas.example")
    args = parser.parse_args()
    report = adapt_export(
        args.zip,
        args.work_root,
        MAPPING,
        h1_fixture_business_config(),
        business_id=H1_BUSINESS_ID,
        api_base_url=args.api_base_url,
        site_origin=args.site_origin,
    )
    summary = {key: report[key] for key in ("ready", "install_seconds", "build", "platform_contract", "truth_contract")}
    summary["artifact"] = {k: v for k, v in report["artifact"].items() if k != "external_links"}
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
