"""HiggsfieldCli — a thin, generic wrapper over the `higgsfield` CLI
binary (see docs/higgsfield-integration.md's "CLI integration status"
section for the full rationale). Every command/flag/response shape here
was verified directly against the real, installed CLI (`higgsfield
--help`, `higgsfield account status --json`, `higgsfield generate cost
... --json`, `higgsfield generate list --json`) before being written —
never invented, per the same "no fabricated endpoint contract" discipline
app.creative.higgsfield.client's docstring already states for the
(unused) HTTP path.

Deliberately generic at this layer — no CreativeDirection-shaped
knowledge, no prompt construction: this module only knows how to run one
`higgsfield <command>` subprocess and parse its `--json` stdout.
app.creative.higgsfield.director is where CreativeBrief-derived prompts
get built and turned into CreativeDirection candidates.

Security: every argument is passed as a real subprocess.run() argv list
(never `shell=True`, never string-interpolated into a shell command), so
arbitrary business text (a business description, a target_customer
string) reaching a `--prompt` argument can never break out into shell
command injection regardless of its content — the same defense
`app.publishing.build.build_site`'s own `subprocess.run(..., cwd=...)`
call relies on. The CLI's own OAuth token (`higgsfield auth token`) is
never read, passed, or logged by this module.
"""

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.creative.errors import CreativeProviderRequestError


class HiggsfieldCliError(CreativeProviderRequestError):
    """The `higgsfield` subprocess failed, timed out, or returned output
    this module couldn't parse as the expected JSON shape."""


class HiggsfieldCliUnavailableError(HiggsfieldCliError):
    """The `higgsfield` binary isn't installed/on PATH, or the local CLI
    session isn't authenticated — see this module's own docstring on why
    this is a machine-local fact, not a per-request credential check."""


@dataclass
class HiggsfieldAccountStatus:
    email: str
    credits: float
    subscription_plan_type: str | None = None


@dataclass
class HiggsfieldJobResult:
    job_id: str
    job_type: str
    status: str
    result_url: str | None
    raw: dict = field(default_factory=dict)


class HiggsfieldCli:
    def __init__(self, *, binary: str = "higgsfield", timeout_seconds: float = 240.0) -> None:
        self._binary = binary
        self._timeout_seconds = timeout_seconds

    def _run(self, args: list[str]) -> Any:
        try:
            result = subprocess.run(
                [self._binary, *args, "--json"],
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise HiggsfieldCliUnavailableError(
                f"The {self._binary!r} CLI binary is not installed/on PATH on this server."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise HiggsfieldCliError(f"higgsfield {' '.join(args)} timed out after {self._timeout_seconds}s") from exc

        if result.returncode != 0:
            raise HiggsfieldCliError(
                f"higgsfield {' '.join(args)} failed (exit {result.returncode}): {_tail(result.stderr)}"
            )

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise HiggsfieldCliError(
                f"higgsfield {' '.join(args)} did not return valid JSON: {_tail(result.stdout)}"
            ) from exc

    def account_status(self) -> HiggsfieldAccountStatus:
        """Also this module's availability check — a fresh
        HiggsfieldCliUnavailableError/HiggsfieldCliError from this call is
        exactly how app.dependencies.get_optional_higgsfield_director
        (P2) reports "not available" without a separate probe path."""
        data = self._run(["account", "status"])
        return HiggsfieldAccountStatus(
            email=data["email"],
            credits=float(data["credits"]),
            subscription_plan_type=data.get("subscription_plan_type"),
        )

    def estimate_cost(self, job_type: str, *, prompt: str) -> float:
        """Read-only — Higgsfield's own cost calculator, never a spend.
        Every real create() call below must be preceded by a matching
        CreativeBudget.record_spend using this estimate, so the budget
        never spends before it knows the real cost of the specific call
        it's about to allow."""
        data = self._run(["generate", "cost", job_type, "--prompt", prompt])
        return float(data["credits"])

    def create(
        self,
        job_type: str,
        *,
        prompt: str,
        image_references: list[str] | None = None,
        aspect_ratio: str | None = None,
        resolution: str | None = None,
        wait_timeout: str = "4m",
    ) -> HiggsfieldJobResult:
        """Creates a real, credit-consuming generation job and blocks
        until it finishes (`--wait`) — the caller must have already
        called estimate_cost + CreativeBudget.record_spend for this exact
        call before invoking this method; this method itself has no
        budget awareness. `image_references` accepts local file paths
        (auto-uploaded by the CLI) or previously-uploaded media ids —
        never a raw URL string interpolated into a shell command (see
        this module's own docstring on argv-list subprocess safety)."""
        args = ["generate", "create", job_type, "--prompt", prompt, "--wait", "--wait-timeout", wait_timeout]
        if image_references:
            for reference in image_references:
                args += ["--image-references", reference]
        if aspect_ratio:
            args += ["--aspect-ratio", aspect_ratio]
        if resolution:
            args += ["--resolution", resolution]

        data = self._run(args)
        # `--wait` on a single-job `create` call returns either the job
        # object directly or a one-element list, depending on CLI
        # version — both observed against the real, installed binary;
        # normalize here rather than assume one shape.
        job = data[0] if isinstance(data, list) else data
        return HiggsfieldJobResult(
            job_id=str(job["id"]),
            job_type=str(job.get("job_type", job_type)),
            status=str(job.get("status", "unknown")),
            result_url=job.get("result_url"),
            raw=job,
        )


def resolve_local_reference(storage_url: str, *, local_storage_root: Path) -> str | None:
    """Best-effort: a BusinessAsset.storage_url served by
    LocalStorageProvider (app.storage.local — the only StorageProvider
    this codebase has today, see that module's own docstring) is an HTTP
    path like `/uploads/<key>`; the CLI needs a real local file path, not
    a URL, to auto-upload a reference image (see HiggsfieldCli.create's
    own docstring). Returns None (never raises) when `storage_url` isn't
    a recognizable local-storage path — a real, network-hosted asset (a
    future S3StorageProvider/R2StorageProvider) simply isn't usable as a
    reference yet; the caller proceeds prompt-only rather than fail the
    whole creative-direction workflow over one unavailable reference
    image."""
    marker = "/uploads/"
    index = storage_url.find(marker)
    if index == -1:
        return None
    relative_key = storage_url[index + len(marker) :]
    candidate = (local_storage_root / relative_key).resolve()
    try:
        candidate.relative_to(local_storage_root.resolve())
    except ValueError:
        return None  # Path traversal attempt in a stored URL — refuse.
    return str(candidate) if candidate.is_file() else None


def _tail(text: str, limit: int = 2000) -> str:
    return text if len(text) <= limit else f"…{text[-limit:]}"
