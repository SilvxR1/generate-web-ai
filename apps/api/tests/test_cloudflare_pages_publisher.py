"""CloudflarePagesClient + CloudflarePagesPublisher: project ensure/lookup
against a mocked Cloudflare REST API (httpx.MockTransport — no real
account needed), and the `wrangler pages deploy` subprocess step against
a monkeypatched `subprocess.run` (no real Node/wrangler invocation) —
that split mirrors the real implementation, which uses the REST API only
for project existence/creation and post-deploy status, and shells out to
wrangler for the actual asset upload (see engine.py's module docstring
for why: a raw-REST direct-upload implementation was confirmed live to
report success at every step while the deployed site 500'd on every
request)."""

import json

import httpx
import pytest

from app.publishing.cloudflare import CloudflareApiError, CloudflarePagesClient, CloudflarePagesPublisher
from app.publishing.errors import WebsitePublisherError
from app.publishing.publisher import WebsiteArtifact

API_TOKEN = "cf-super-secret-api-token"
ACCOUNT_ID = "acct-1"


def _publisher(handler) -> CloudflarePagesPublisher:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, base_url="https://api.cloudflare.com/client/v4")
    client = CloudflarePagesClient(ACCOUNT_ID, API_TOKEN, http_client=http_client)
    return CloudflarePagesPublisher(client, account_id=ACCOUNT_ID, api_token=API_TOKEN)


def _artifact() -> WebsiteArtifact:
    return WebsiteArtifact(files={"index.html": b"<html>hi</html>", "_astro/index.css": b"body{color:red}"})


def _project_exists_handler(has_deployment: bool = True):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        result: dict[str, object] = {"name": "site-1"}
        if has_deployment:
            result["latest_deployment"] = {"id": "dep-1"}
        return httpx.Response(200, json={"success": True, "result": result, "errors": []})

    return handler


def _mock_successful_wrangler(monkeypatch: pytest.MonkeyPatch, calls: list | None = None) -> None:
    def fake_run(cmd, **kwargs):
        if calls is not None:
            calls.append((cmd, kwargs))
        return _FakeCompletedProcess(returncode=0, stdout="✨ Deployment complete!", stderr="")

    monkeypatch.setattr("app.publishing.cloudflare.engine.subprocess.run", fake_run)


class _FakeCompletedProcess:
    def __init__(self, *, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# --- publish: project ensure + wrangler deploy + status lookup --------------


def test_publish_creates_project_if_missing_then_deploys_via_wrangler(monkeypatch: pytest.MonkeyPatch, tmp_path):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path == "/client/v4/accounts/acct-1/pages/projects/site-1" and request.method == "GET":
            return httpx.Response(404, json={"success": False, "errors": [{"message": "not found"}]})
        if path == "/client/v4/accounts/acct-1/pages/projects" and request.method == "POST":
            return httpx.Response(200, json={"success": True, "result": {"name": "site-1"}, "errors": []})
        raise AssertionError(f"unexpected request: {request.method} {path}")

    wrangler_calls: list = []
    _mock_successful_wrangler(monkeypatch, wrangler_calls)

    # get_project (post-deploy status check) needs its own handler swap
    # since project creation used a 404-then-create sequence above.
    def status_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"success": True, "result": {"name": "site-1", "latest_deployment": {"id": "dep-1"}}, "errors": []},
        )

    # Swap the transport's handler after ensure_project's calls happen by
    # using a stateful handler instead.
    call_count = {"n": 0}

    def combined_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] <= 2:
            return handler(request)
        return status_handler(request)

    publisher = _publisher(combined_handler)
    result = publisher.publish(site_id="site-1", artifact=_artifact())

    assert result.deployment_id == "site-1::dep-1"
    assert str(result.url) == "https://site-1.pages.dev/"
    assert result.live is True
    assert len(wrangler_calls) == 1
    cmd, kwargs = wrangler_calls[0]
    assert cmd[:4] == ["npx", "wrangler", "pages", "deploy"]
    assert "--project-name=site-1" in cmd
    assert kwargs["env"]["CLOUDFLARE_ACCOUNT_ID"] == ACCOUNT_ID
    assert kwargs["env"]["CLOUDFLARE_API_TOKEN"] == API_TOKEN


def test_publish_materializes_the_artifact_files_wrangler_deploys(monkeypatch: pytest.MonkeyPatch):
    publisher = _publisher(_project_exists_handler())
    captured_dirs: list = []

    def fake_run(cmd, **kwargs):
        from pathlib import Path

        artifact_dir = Path(cmd[4])
        captured_dirs.append(artifact_dir)
        assert (artifact_dir / "index.html").read_bytes() == b"<html>hi</html>"
        assert (artifact_dir / "_astro" / "index.css").read_bytes() == b"body{color:red}"
        return _FakeCompletedProcess(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("app.publishing.cloudflare.engine.subprocess.run", fake_run)

    publisher.publish(site_id="site-1", artifact=_artifact())

    assert len(captured_dirs) == 1
    # The temp directory is cleaned up after publish() returns.
    assert not captured_dirs[0].exists()


def test_publish_skips_project_creation_when_it_already_exists(monkeypatch: pytest.MonkeyPatch):
    creation_attempts: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/client/v4/accounts/acct-1/pages/projects" and request.method == "POST":
            creation_attempts.append(request)
        return _project_exists_handler()(request)

    publisher = _publisher(handler)
    _mock_successful_wrangler(monkeypatch)

    publisher.publish(site_id="site-1", artifact=_artifact())

    assert creation_attempts == []


def test_publish_never_leaks_the_api_token_in_the_result(monkeypatch: pytest.MonkeyPatch):
    publisher = _publisher(_project_exists_handler())
    _mock_successful_wrangler(monkeypatch)

    result = publisher.publish(site_id="site-1", artifact=_artifact())

    dumped = json.dumps(result.model_dump(mode="json"))
    assert API_TOKEN not in dumped
    assert API_TOKEN not in repr(result)


def test_publish_rejects_an_invalid_site_id_before_any_request(monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not call Cloudflare with an invalid project name")

    publisher = _publisher(handler)

    def fake_run(cmd, **kwargs):
        raise AssertionError("must not invoke wrangler with an invalid project name")

    monkeypatch.setattr("app.publishing.cloudflare.engine.subprocess.run", fake_run)

    with pytest.raises(WebsitePublisherError):
        publisher.publish(site_id="Not Valid!", artifact=_artifact())


def test_publish_rejects_when_status_check_finds_no_deployment(monkeypatch: pytest.MonkeyPatch):
    publisher = _publisher(_project_exists_handler(has_deployment=False))
    _mock_successful_wrangler(monkeypatch)

    with pytest.raises(WebsitePublisherError):
        publisher.publish(site_id="site-1", artifact=_artifact())


def test_publish_propagates_a_wrangler_failure():
    publisher = _publisher(_project_exists_handler())

    with pytest.MonkeyPatch.context() as mp:

        def fake_run(cmd, **kwargs):
            return _FakeCompletedProcess(returncode=1, stdout="", stderr="Error: authentication failed")

        mp.setattr("app.publishing.cloudflare.engine.subprocess.run", fake_run)

        with pytest.raises(WebsitePublisherError, match="authentication failed"):
            publisher.publish(site_id="site-1", artifact=_artifact())


def test_publish_propagates_a_project_creation_http_error(monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(404, json={"success": False, "errors": [{"message": "not found"}]})
        return httpx.Response(500, text="internal server error")

    publisher = _publisher(handler)

    def fake_run(cmd, **kwargs):
        raise AssertionError("must not invoke wrangler when project creation itself failed")

    monkeypatch.setattr("app.publishing.cloudflare.engine.subprocess.run", fake_run)

    with pytest.raises(CloudflareApiError):
        publisher.publish(site_id="site-1", artifact=_artifact())


# --- get_status -------------------------------------------------------------


def test_get_status_reports_live_when_project_has_a_deployment():
    publisher = _publisher(_project_exists_handler(has_deployment=True))

    result = publisher.get_status("site-1::dep-1")

    assert result.live is True
    assert str(result.url) == "https://site-1.pages.dev/"


def test_get_status_reports_not_live_when_project_has_no_deployment():
    publisher = _publisher(_project_exists_handler(has_deployment=False))

    result = publisher.get_status("site-1::dep-1")

    assert result.live is False
