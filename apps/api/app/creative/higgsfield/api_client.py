"""HiggsfieldApiClient — the official Higgsfield REST API client (P2.1
production path), replacing the local `higgsfield` CLI/OAuth session as
the production Creative Director backend. Authenticates with a server-side
API key pair (`Authorization: Key <KEY_ID>:<KEY_SECRET>`, created in
Higgsfield Cloud — cloud.higgsfield.ai), verified against the officially
published OpenAPI spec at docs.higgsfield.ai/docs/openapi.json, never
invented — see docs/higgsfield-integration.md for exactly what was checked
and how.

Endpoint/job-type mapping is deliberately an explicit, small allowlist
(_ENDPOINT_PATHS) rather than a generic "pass any job_type as a path
segment" — Nano Banana Pro (the CLI's own default model) does not appear
anywhere in the published REST OpenAPI spec, so this client refuses to
guess a path for it rather than silently hitting a URL that may not exist
or may not mean what the name implies (see this module's own
DEFAULT_JOB_TYPE and docs/higgsfield-integration.md's "REST endpoint
verification" section for the exact paths confirmed).

Never retries the submission (POST) call automatically — a retried submit
would double-spend real Higgsfield credits — only the read-only status
poll (GET, idempotent, never billed) retries a bounded number of times on
a transient network error.
"""

import ipaddress
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.creative.errors import CreativeProviderRequestError
from app.creative.higgsfield.models import HiggsfieldJobResult


class HiggsfieldApiError(CreativeProviderRequestError):
    """A Higgsfield REST API call failed — network error, timeout, a
    non-2xx response, or a request that reached a `failed`/`nsfw`/
    `canceled` terminal state. Never carries the API key or raw
    Authorization header in its message."""


class HiggsfieldApiUnavailableError(HiggsfieldApiError):
    """The API key pair isn't configured, or Higgsfield rejected it
    outright (401) — this integration cannot run at all right now, as
    opposed to one specific call failing. Mirrors
    app.creative.higgsfield.cli.HiggsfieldCliUnavailableError's role for
    the CLI backend."""


# Confirmed directly against the published OpenAPI spec
# (docs.higgsfield.ai/docs/openapi.json) — every value here is a real path
# from that document, never a guess. Extend this table (and re-verify
# against the spec) before adding a new job type; never construct a path
# from a job_type string.
_ENDPOINT_PATHS: dict[str, str] = {
    "nano-banana": "/nano-banana",
}

DEFAULT_JOB_TYPE = "nano-banana"

_TERMINAL_STATUSES = frozenset({"completed", "failed", "nsfw", "canceled"})
_MAX_INPUT_IMAGES = 8


@dataclass
class _SubmitResponse:
    request_id: str
    status_url: str
    cancel_url: str


def _validate_reference_url(url: str) -> str:
    """Defense-in-depth against SSRF/unsafe outgoing reference URLs
    (P2.1 threat model): every URL this client sends to Higgsfield as an
    `image_url` must be a real, public `https://` URL — never a
    `file://`/`javascript:` scheme, a bare IP a caller could point at
    internal infrastructure, or an empty/malformed value. `storage_url`
    values in this codebase are always generated internally (see
    app.storage.keys.generate_storage_key), never taken from raw user
    input, but this check stays as the same "never trust a URL string
    just because it looks like one" discipline
    app.creative.higgsfield.cli.resolve_local_reference already applies to
    local paths."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise HiggsfieldApiError(f"Refusing to send a non-https reference URL to Higgsfield: {url!r}")
    try:
        ip = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        ip = None
    if ip is not None and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved):
        raise HiggsfieldApiError(f"Refusing to send an internal/private reference URL to Higgsfield: {url!r}")
    if parsed.hostname in {"localhost"}:
        raise HiggsfieldApiError(f"Refusing to send a localhost reference URL to Higgsfield: {url!r}")
    return url


def _parse_wait_timeout(wait_timeout: str) -> float:
    """Parses the same "4m"/"30s"/"1h" shape
    app.creative.higgsfield.cli.HiggsfieldCli.create's `wait_timeout`
    already accepts, for interface parity between the two backends."""
    if wait_timeout.endswith("ms"):
        return float(wait_timeout[:-2]) / 1000.0
    unit = wait_timeout[-1]
    multipliers = {"s": 1.0, "m": 60.0, "h": 3600.0}
    if unit in multipliers:
        return float(wait_timeout[:-1]) * multipliers[unit]
    return float(wait_timeout)


def _tail(text: str, limit: int = 500) -> str:
    return text if len(text) <= limit else f"…{text[-limit:]}"


def _raise_for_status(response: httpx.Response, context: str) -> None:
    if response.status_code == 401:
        raise HiggsfieldApiUnavailableError(
            "Higgsfield rejected the configured API key pair (401 Unauthorized)."
        )
    if response.status_code >= 400:
        raise HiggsfieldApiError(
            f"Higgsfield API error ({response.status_code}) calling {context}: {_tail(response.text)}"
        )


class HiggsfieldApiClient:
    def __init__(
        self,
        *,
        key_id: str | None,
        key_secret: str | None,
        base_url: str = "https://api.higgsfield.ai",
        timeout_seconds: float = 60.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not key_id or not key_secret:
            raise HiggsfieldApiUnavailableError(
                "HIGGSFIELD_API_KEY_ID/HIGGSFIELD_API_KEY_SECRET are not configured on this server."
            )
        # Never stored/logged separately from this header value, and this
        # value itself is never included in any exception message or log
        # line anywhere in this module.
        self._auth_header = f"Key {key_id}:{key_secret}"
        timeout = httpx.Timeout(connect=10.0, read=timeout_seconds, write=10.0, pool=10.0)
        self._client = http_client or httpx.Client(base_url=base_url, timeout=timeout)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": self._auth_header, "Content-Type": "application/json"}

    def submit(
        self,
        job_type: str,
        *,
        prompt: str,
        image_references: list[str] | None = None,
        aspect_ratio: str | None = None,
        num_images: int | None = None,
    ) -> _SubmitResponse:
        """Submits one generation request — never retried automatically
        (a retried POST could double-spend real credits; see this
        module's own docstring)."""
        path = _ENDPOINT_PATHS.get(job_type)
        if path is None:
            raise HiggsfieldApiError(
                f"{job_type!r} has no known official Higgsfield REST endpoint in this client's allowlist "
                f"({sorted(_ENDPOINT_PATHS)}) — see this module's own docstring."
            )
        body: dict = {"prompt": prompt}
        if aspect_ratio:
            body["aspect_ratio"] = aspect_ratio
        if num_images:
            body["num_images"] = num_images
        if image_references:
            body["input_images"] = [
                {"type": "image_url", "image_url": _validate_reference_url(url)}
                for url in image_references[:_MAX_INPUT_IMAGES]
            ]

        try:
            response = self._client.post(path, headers=self._headers(), json=body)
        except httpx.TimeoutException as exc:
            raise HiggsfieldApiError(f"Higgsfield request to {path} timed out.") from exc
        except httpx.HTTPError as exc:
            raise HiggsfieldApiError(f"Higgsfield request to {path} failed: {type(exc).__name__}") from exc
        _raise_for_status(response, path)
        data = response.json()
        return _SubmitResponse(
            request_id=data["request_id"], status_url=data["status_url"], cancel_url=data["cancel_url"]
        )

    def get_status(self, status_url: str) -> dict:
        """Read-only, idempotent, never billed — safe to retry a bounded
        number of times on a transient network error, unlike submit().
        `status_url` is always one Higgsfield itself returned from a
        submit() this process made, never an arbitrary caller-supplied
        URL, so this is not an SSRF surface."""
        last_exc: httpx.TimeoutException | None = None
        for attempt in range(3):
            try:
                response = self._client.get(status_url, headers=self._headers())
                _raise_for_status(response, status_url)
                return response.json()
            except httpx.TimeoutException as exc:
                last_exc = exc
                if attempt < 2:
                    time.sleep(1.0 * (attempt + 1))
                    continue
            except httpx.HTTPError as exc:
                raise HiggsfieldApiError(f"Failed polling Higgsfield status: {type(exc).__name__}") from exc
        raise HiggsfieldApiError(f"Timed out polling {status_url}.") from last_exc

    def cancel(self, cancel_url: str) -> None:
        try:
            response = self._client.post(cancel_url, headers=self._headers())
        except httpx.HTTPError as exc:
            raise HiggsfieldApiError(f"Failed to cancel Higgsfield request: {type(exc).__name__}") from exc
        if response.status_code not in (200, 204, 404):
            _raise_for_status(response, cancel_url)

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
        """Submit + poll to a terminal state — the same blocking shape
        app.creative.higgsfield.cli.HiggsfieldCli.create's own `--wait`
        gives the CLI backend, so app.creative.higgsfield.director's
        shared orchestration logic can call either backend identically.
        `resolution` is accepted only for interface parity with the CLI
        backend (Nano Banana has no resolution parameter) and ignored."""
        del resolution
        submitted = self.submit(
            job_type, prompt=prompt, image_references=image_references, aspect_ratio=aspect_ratio
        )
        deadline = time.monotonic() + _parse_wait_timeout(wait_timeout)
        poll_interval = 2.0
        data: dict = {}
        status = "queued"
        while True:
            data = self.get_status(submitted.status_url)
            status = data.get("status", "queued")
            if status in _TERMINAL_STATUSES:
                break
            if time.monotonic() >= deadline:
                raise HiggsfieldApiError(
                    f"Higgsfield request {submitted.request_id} did not reach a terminal state "
                    f"within {wait_timeout}."
                )
            time.sleep(poll_interval)
            poll_interval = min(poll_interval * 1.5, 10.0)

        if status == "failed":
            raise HiggsfieldApiError(f"Higgsfield request {submitted.request_id} failed: {data.get('error')}")
        if status == "nsfw":
            raise HiggsfieldApiError(
                f"Higgsfield request {submitted.request_id} was flagged NSFW (not charged)."
            )
        if status == "canceled":
            raise HiggsfieldApiError(f"Higgsfield request {submitted.request_id} was canceled.")

        images = data.get("images") or []
        result_url = images[0]["url"] if images and "url" in images[0] else None
        return HiggsfieldJobResult(
            job_id=submitted.request_id, job_type=job_type, status=status, result_url=result_url, raw=data
        )
