"""The artifact fetcher and the generated-image QA service (P2.7).

The fetcher is the network boundary (a provider result URL), so its guards are
tested exhaustively over httpx.MockTransport — no real network. The service is
tested with in-memory fakes: it must record QA in provenance, degrade every
infrastructure problem to NOT_PERFORMED (never a pass, never a block), and never
raise into a completed generation."""

import json
from io import BytesIO

import httpx
import pytest
from PIL import Image

from app.creative.artifact_fetcher import (
    ArtifactFetchError,
    DisabledArtifactFetcher,
    HttpsArtifactFetcher,
)
from app.domain.creative.image_qa import CheckStatus
from app.services.generated_image_qa import GeneratedImageQAService, attach_image_qa
from tests.test_creative_director import _direction

URL = "https://d3example.cloudfront.net/abc/out.png"


def _png(size=(320, 180), color=(211, 205, 191)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def _fetcher(handler, **kwargs) -> HttpsArtifactFetcher:
    return HttpsArtifactFetcher(http_client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)


# --- the fetcher: an untrusted network boundary ------------------------------------------------


def test_a_provider_url_is_fetched_over_https():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"bytes")

    assert _fetcher(handler).fetch(URL) == b"bytes"
    assert seen[0].method == "GET" and seen[0].url.scheme == "https"
    assert "authorization" not in seen[0].headers  # no credential is ever attached


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://d3example.cloudfront.net/a.png",  # plain http
        "ftp://d3example.cloudfront.net/a.png",
        "https://localhost/a.png",
        "https://api.localhost/a.png",
        "https://printer.local/a.png",
        "https://127.0.0.1/a.png",
        "https://10.0.0.5/a.png",
        "https://192.168.1.10/a.png",
        "https://169.254.169.254/latest/meta-data",  # cloud metadata endpoint
        "https://[::1]/a.png",
        "https://0.0.0.0/a.png",
        "https://user:secret@d3example.cloudfront.net/a.png",  # credentials in the URL
        "not a url",
    ],
)
def test_unsafe_urls_are_refused_before_any_request(url: str):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request may be made for an unsafe URL")

    with pytest.raises(ArtifactFetchError) as caught:
        _fetcher(handler).fetch(url)
    assert caught.value.code == "invalid_url"


def test_redirects_are_not_followed():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://169.254.169.254/latest"})

    with pytest.raises(ArtifactFetchError) as caught:
        _fetcher(handler).fetch(URL)
    assert caught.value.code == "http_error" and calls == [URL]  # the redirect target was never contacted


@pytest.mark.parametrize("status", [403, 404, 500])
def test_a_non_200_response_is_an_http_error(status: int):
    with pytest.raises(ArtifactFetchError) as caught:
        _fetcher(lambda request: httpx.Response(status)).fetch(URL)
    assert caught.value.code == "http_error"


def test_a_declared_size_over_the_cap_is_refused_without_reading_the_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-length": "5000"}, content=b"")

    with pytest.raises(ArtifactFetchError) as caught:
        _fetcher(handler, max_bytes=1000).fetch(URL)
    assert caught.value.code == "too_large"


def test_a_streamed_body_over_the_cap_is_cut_off_without_a_declared_length():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=iter([b"x" * 600, b"x" * 600, b"x" * 600]))  # no content-length

    with pytest.raises(ArtifactFetchError) as caught:
        _fetcher(handler, max_bytes=1000).fetch(URL)
    assert caught.value.code == "too_large"


def test_the_default_cap_is_the_p26_image_byte_limit():
    from app.domain.creative.brand_intelligence import MAX_IMAGE_BYTES

    assert HttpsArtifactFetcher()._max_bytes == MAX_IMAGE_BYTES  # one limit across P2.6 and P2.7


@pytest.mark.parametrize(
    ("error", "code"),
    [(httpx.ReadTimeout("slow"), "timeout"), (httpx.ConnectError("refused"), "network_error")],
)
def test_transport_failures_map_to_stable_codes(error: Exception, code: str):
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    with pytest.raises(ArtifactFetchError) as caught:
        _fetcher(handler).fetch(URL)
    assert caught.value.code == code


def test_the_error_never_carries_the_url():
    with pytest.raises(ArtifactFetchError) as caught:
        _fetcher(lambda request: httpx.Response(404)).fetch(URL)
    assert URL not in str(caught.value) and "cloudfront" not in str(caught.value)


def test_the_disabled_fetcher_fetches_nothing():
    with pytest.raises(ArtifactFetchError) as caught:
        DisabledArtifactFetcher().fetch(URL)
    assert caught.value.code == "disabled"


# --- the service ---------------------------------------------------------------------------------


class MapFetcher:
    def __init__(self, mapping: dict[str, bytes] | None = None, error: Exception | None = None) -> None:
        self.mapping, self.error, self.calls = mapping or {}, error, []

    def fetch(self, url: str) -> bytes:
        self.calls.append(url)
        if self.error is not None:
            raise self.error
        return self.mapping[url]


def _generated(**spec_overrides):
    spec = {
        "purpose": "hero",
        "scene_plan": {
            "aspect_ratio": "16:9",
            "subject_side": "right",
            "brand_palette": ["#EDB08D", "#8A6985", "#EA7D87"],
        },
        "validation": {
            "status": "passed",
            "checks": [],
            "visual_qa": "not_performed",
            "not_covered": ["unwanted_text"],
        },
        **spec_overrides,
    }
    return _direction(references=[URL], generation_metadata={"creative_spec": spec})


def test_the_service_evaluates_the_recorded_requirements_against_the_fetched_bytes():
    candidate = _generated()
    service = GeneratedImageQAService(MapFetcher({URL: _png((1696, 960))}))

    result = service.evaluate(candidate)

    assert result is not None and result.requirements.brand_palette == ("#EDB08D", "#8A6985", "#EA7D87")
    assert next(c for c in result.checks if c.name == "aspect_ratio").status is CheckStatus.PASS
    assert next(c for c in result.checks if c.name == "brand_palette_adherence").status is CheckStatus.WARNING


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (ArtifactFetchError("timeout"), "artifact_unavailable"),
        (ArtifactFetchError("http_error"), "artifact_unavailable"),  # an expired URL
        (ArtifactFetchError("too_large"), "analysis_limits_exceeded"),
    ],
)
def test_an_unretrievable_artifact_is_not_performed_never_pass_never_block(error: ArtifactFetchError, reason: str):
    result = GeneratedImageQAService(MapFetcher(error=error)).evaluate(_generated())

    assert result is not None and result.overall_status is CheckStatus.NOT_PERFORMED
    assert result.approval_eligible is True
    assert all(check.status is CheckStatus.NOT_PERFORMED for check in result.checks)
    assert result.checks[0].reason == reason and result.checks[0].evidence == {"fetch_error": error.code}


def test_a_candidate_without_a_generated_image_is_not_evaluated_and_nothing_is_claimed():
    fetcher = MapFetcher()
    service = GeneratedImageQAService(fetcher)

    no_references = _direction(references=[], generation_metadata={"creative_spec": {"purpose": "hero"}})
    no_provenance = _direction(references=[URL], generation_metadata={})
    assert service.evaluate(no_references) is None
    assert service.evaluate(_generated(generated_image=False)) is None  # an internal-fallback direction
    assert service.evaluate(no_provenance) is None
    assert fetcher.calls == []


def test_attach_records_qa_in_provenance_and_corrects_the_static_validation_fields():
    candidate = _generated()

    attach_image_qa(candidate, GeneratedImageQAService(MapFetcher({URL: _png((1696, 960))})))

    spec = candidate.generation_metadata["creative_spec"]
    assert spec["visual_qa"]["version"] == "p2.7-v1" and spec["visual_qa"]["approval_eligible"] is True
    assert spec["validation"]["visual_qa"] == "performed"  # was the static "not_performed"
    assert "unwanted_text" in spec["validation"]["not_covered"] and len(spec["validation"]["not_covered"]) == 7
    assert spec["validation"]["status"] == "passed"  # the metadata verdict is untouched


def test_attach_when_nothing_could_be_checked_keeps_visual_qa_not_performed():
    candidate = _generated()

    attach_image_qa(candidate, GeneratedImageQAService(DisabledArtifactFetcher()))

    spec = candidate.generation_metadata["creative_spec"]
    assert spec["visual_qa"]["overall_status"] == "not_performed"
    assert spec["validation"]["visual_qa"] == "not_performed"


def test_attach_never_records_the_result_url_or_any_credential():
    candidate = _generated()

    attach_image_qa(candidate, GeneratedImageQAService(MapFetcher({URL: _png((1696, 960))})))

    dumped = json.dumps(candidate.generation_metadata)
    assert URL not in dumped and "cloudfront" not in dumped
    for forbidden in ("X-Amz", "presign", "Authorization", "secret"):
        assert forbidden not in dumped


def test_attach_never_raises_even_if_the_fetcher_explodes():
    candidate = _generated()

    attach_image_qa(candidate, GeneratedImageQAService(MapFetcher(error=RuntimeError("boom"))))  # not a fetch error

    qa = candidate.generation_metadata["creative_spec"]["visual_qa"]
    assert qa["overall_status"] == "not_performed" and qa["approval_eligible"] is True
    assert qa["checks"][0]["reason"] == "qa_error"


def test_attach_ignores_a_candidate_with_no_provenance():
    candidate = _direction(references=[URL], generation_metadata={})

    attach_image_qa(candidate, GeneratedImageQAService(MapFetcher()))

    assert candidate.generation_metadata == {}


def test_a_blocking_image_is_recorded_as_ineligible():
    candidate = _generated()

    attach_image_qa(candidate, GeneratedImageQAService(MapFetcher({URL: _png((1500, 1000))})))  # 3:2

    qa = candidate.generation_metadata["creative_spec"]["visual_qa"]
    assert qa["approval_eligible"] is False and qa["overall_status"] == "fail"
    assert qa["blocking_reasons"] and "aspect_ratio" in qa["blocking_reasons"][0]
