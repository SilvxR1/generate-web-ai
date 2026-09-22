"""Fetching a generated artifact's bytes for Image QA (P2.7).

Why this exists: generated images are NOT persisted to our own storage today —
the only trace of one is the provider's result URL on the direction. QA
therefore needs the bytes while that URL is fresh, i.e. immediately after the
provider completed (see app.services.generated_image_qa). Persisting generated
artifacts to a StorageProvider is the durable fix and is deferred; this module
is the ArtifactFetcher SEAM that persistent storage would later implement.

Hard bounds, because a provider URL is still an untrusted network boundary:
https only, no credentials in the URL, no localhost / private / link-local /
reserved IP literals, NO redirect following, a streaming size cap (the P2.6
image byte limit) and a timeout. Never logs or returns the URL.

Known limitation: hostnames are validated syntactically, not resolved, so DNS
rebinding is not defended against; the URL comes from the provider's own API
response, not from a user.
"""

import ipaddress
from typing import Protocol
from urllib.parse import urlparse

import httpx

from app.domain.creative.brand_intelligence import MAX_IMAGE_BYTES

DEFAULT_TIMEOUT_SECONDS = 15.0


class ArtifactFetchError(Exception):
    """`code` is a stable machine code: invalid_url, http_error, too_large,
    timeout, network_error, disabled."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ArtifactFetcher(Protocol):
    def fetch(self, url: str) -> bytes: ...


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    host = parsed.hostname
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise ArtifactFetchError("invalid_url")
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise ArtifactFetchError("invalid_url")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return  # a hostname, not an IP literal
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
        raise ArtifactFetchError("invalid_url")


class HttpsArtifactFetcher:
    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_bytes: int = MAX_IMAGE_BYTES,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._max_bytes = max_bytes
        self._client = http_client

    def fetch(self, url: str) -> bytes:
        _validate_url(url)
        client = self._client or httpx.Client(timeout=self._timeout, follow_redirects=False)
        try:
            with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise ArtifactFetchError("http_error")
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > self._max_bytes:
                    raise ArtifactFetchError("too_large")
                buffer = bytearray()
                for chunk in response.iter_bytes():
                    buffer.extend(chunk)
                    if len(buffer) > self._max_bytes:
                        raise ArtifactFetchError("too_large")
            return bytes(buffer)
        except ArtifactFetchError:
            raise
        except httpx.TimeoutException as exc:
            raise ArtifactFetchError("timeout") from exc
        except httpx.HTTPError as exc:
            raise ArtifactFetchError("network_error") from exc
        finally:
            if self._client is None:
                client.close()


class DisabledArtifactFetcher:
    """Fetches nothing. Used where real network access must not happen (tests);
    every QA check then reports NOT_PERFORMED, never a pass."""

    def fetch(self, url: str) -> bytes:
        raise ArtifactFetchError("disabled")
