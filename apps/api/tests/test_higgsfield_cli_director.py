"""HiggsfieldCli / HiggsfieldCliCreativeDirector (app.creative.higgsfield.cli,
app.creative.higgsfield.director) — subprocess mocked throughout (no real
Higgsfield credits spent by this test module); verifies the budget-before-
spend discipline, candidate/reference propagation, and graceful partial
results on a mid-workflow failure."""

import json
import subprocess
from dataclasses import dataclass
from unittest.mock import patch

import pytest

from app.creative.higgsfield.cli import HiggsfieldCli, HiggsfieldCliError, HiggsfieldCliUnavailableError
from app.creative.higgsfield.director import HiggsfieldCliCreativeDirector
from app.domain.business_config import BusinessConfig, BusinessProfile
from app.domain.creative.brief import build_creative_brief
from app.domain.creative.budget import CreativeBudget
from app.domain.enums import BusinessVertical, CreativeBudgetTier


@dataclass
class _FakeCompletedProcess:
    returncode: int
    stdout: str
    stderr: str = ""


def _brief():
    config = BusinessConfig(
        business_profile=BusinessProfile(
            name="Cositas y Puntos",
            slug="cositas-y-puntos",
            industry=BusinessVertical.OTHER,
            description="Amigurumi hechos a mano.",
        )
    )
    return build_creative_brief(business_config=config)


# --- HiggsfieldCli -------------------------------------------------------


def test_cli_account_status_parses_real_response_shape():
    cli = HiggsfieldCli()
    payload = json.dumps({"credits": 1108, "email": "user@example.com", "subscription_plan_type": "plus"})
    with patch("subprocess.run", return_value=_FakeCompletedProcess(0, payload)) as mocked:
        status = cli.account_status()
    assert status.credits == 1108
    assert status.email == "user@example.com"
    assert mocked.call_args.args[0][:2] == ["higgsfield", "account"]


def test_cli_estimate_cost_parses_real_response_shape():
    cli = HiggsfieldCli()
    with patch("subprocess.run", return_value=_FakeCompletedProcess(0, json.dumps({"credits": 2}))):
        assert cli.estimate_cost("nano_banana_pro", prompt="x") == 2.0


def test_cli_create_normalizes_list_or_dict_response():
    cli = HiggsfieldCli()
    job_payload = {"id": "job-1", "job_type": "nano_banana_pro", "status": "completed", "result_url": "https://x/y.png"}
    with patch("subprocess.run", return_value=_FakeCompletedProcess(0, json.dumps([job_payload]))):
        job = cli.create("nano_banana_pro", prompt="x")
    assert job.job_id == "job-1"
    assert job.result_url == "https://x/y.png"


def test_cli_raises_on_nonzero_exit():
    cli = HiggsfieldCli()
    with patch("subprocess.run", return_value=_FakeCompletedProcess(1, "", "boom")):
        with pytest.raises(HiggsfieldCliError):
            cli.account_status()


def test_cli_raises_unavailable_when_binary_missing():
    cli = HiggsfieldCli(binary="nonexistent-higgsfield-binary")
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        with pytest.raises(HiggsfieldCliUnavailableError):
            cli.account_status()


def test_cli_never_uses_a_shell_string(monkeypatch: pytest.MonkeyPatch):
    """Security: subprocess.run must always receive an argv list, never
    shell=True — arbitrary business text in a prompt must never be able
    to break out into shell command injection."""
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _FakeCompletedProcess(0, json.dumps({"credits": 2}))

    monkeypatch.setattr(subprocess, "run", fake_run)
    HiggsfieldCli().estimate_cost("nano_banana_pro", prompt="; rm -rf / #")

    assert isinstance(captured["args"], list)
    assert captured["kwargs"].get("shell", False) is False
    assert "; rm -rf / #" in captured["args"]  # passed as one argv element, not shell-interpreted


# --- HiggsfieldCliCreativeDirector -------------------------------------------


def _job_response(job_id: str, url: str) -> str:
    return json.dumps({"id": job_id, "job_type": "nano_banana_pro", "status": "completed", "result_url": url})


def test_create_directions_produces_three_candidates_and_records_spend():
    brief = _brief()
    budget = CreativeBudget.for_tier(CreativeBudgetTier.STANDARD)
    director = HiggsfieldCliCreativeDirector(HiggsfieldCli())

    responses = iter(
        [
            _FakeCompletedProcess(0, json.dumps({"credits": 2})),
            _FakeCompletedProcess(0, _job_response("job-1", "https://x/1.png")),
            _FakeCompletedProcess(0, json.dumps({"credits": 2})),
            _FakeCompletedProcess(0, _job_response("job-2", "https://x/2.png")),
            _FakeCompletedProcess(0, json.dumps({"credits": 2})),
            _FakeCompletedProcess(0, _job_response("job-3", "https://x/3.png")),
        ]
    )
    with patch("subprocess.run", side_effect=lambda *a, **k: next(responses)):
        candidates = director.create_directions(brief, [], budget)

    assert len(candidates) == 3
    assert budget.credits_used == 6.0
    assert {candidate.references[0] for candidate in candidates} == {
        "https://x/1.png",
        "https://x/2.png",
        "https://x/3.png",
    }
    assert all(candidate.constraints.prohibited_claims for candidate in candidates)
    assert all(brief.business_name in candidate.concept.narrative for candidate in candidates)


def test_create_directions_stops_gracefully_on_budget_exhaustion():
    brief = _brief()
    # Hard limit only covers 2 of the 3 exploration calls (2 credits each).
    budget = CreativeBudget.for_tier(CreativeBudgetTier.EXPERIMENTAL, hard_limit=4.0)
    director = HiggsfieldCliCreativeDirector(HiggsfieldCli())

    responses = iter(
        [
            _FakeCompletedProcess(0, json.dumps({"credits": 2})),
            _FakeCompletedProcess(0, _job_response("job-1", "https://x/1.png")),
            _FakeCompletedProcess(0, json.dumps({"credits": 2})),
            _FakeCompletedProcess(0, _job_response("job-2", "https://x/2.png")),
        ]
    )
    with patch("subprocess.run", side_effect=lambda *a, **k: next(responses)):
        candidates = director.create_directions(brief, [], budget)

    assert len(candidates) == 2  # third would exceed the hard limit — refused before any call
    assert budget.credits_used == 4.0


def test_create_directions_raises_when_zero_candidates_could_be_afforded():
    brief = _brief()
    budget = CreativeBudget.for_tier(CreativeBudgetTier.EXPERIMENTAL, hard_limit=1.0)  # below even one 2-credit call
    director = HiggsfieldCliCreativeDirector(HiggsfieldCli())

    with patch("subprocess.run", return_value=_FakeCompletedProcess(0, json.dumps({"credits": 2}))):
        with pytest.raises(RuntimeError):
            director.create_directions(brief, [], budget)

    assert budget.credits_used == 0.0


def test_develop_direction_anchors_on_the_selected_jobs_id_and_appends_references():
    brief = _brief()
    budget = CreativeBudget.for_tier(CreativeBudgetTier.STANDARD)
    director = HiggsfieldCliCreativeDirector(HiggsfieldCli())

    with patch(
        "subprocess.run",
        side_effect=[
            _FakeCompletedProcess(0, json.dumps({"credits": 2})),
            _FakeCompletedProcess(0, _job_response("job-1", "https://x/1.png")),
        ],
    ):
        [selected] = director.create_directions(brief, [], budget)
    assert selected.provider_metadata["job_id"] == "job-1"

    develop_responses = iter(
        [
            _FakeCompletedProcess(0, json.dumps({"credits": 2})),
            _FakeCompletedProcess(0, _job_response("job-1a", "https://x/1a.png")),
            _FakeCompletedProcess(0, json.dumps({"credits": 2})),
            _FakeCompletedProcess(0, _job_response("job-1b", "https://x/1b.png")),
            _FakeCompletedProcess(0, json.dumps({"credits": 2})),
            _FakeCompletedProcess(0, _job_response("job-1c", "https://x/1c.png")),
        ]
    )
    with patch("subprocess.run", side_effect=lambda *a, **k: next(develop_responses)) as mocked:
        developed = director.develop_direction(selected, brief, [], budget)

    assert developed.concept.name == selected.concept.name  # same direction, not a new concept
    assert set(developed.references) == {
        "https://x/1.png",
        "https://x/1a.png",
        "https://x/1b.png",
        "https://x/1c.png",
    }
    assert developed.generation_metadata["stage"] == "developed"
    assert budget.credits_used == 8.0  # 1 initial (2) + 3 develop calls (2 each)
    # The develop calls reference the selected direction's own job id, not a re-upload.
    create_call_args = [call.args[0] for call in mocked.call_args_list if "create" in call.args[0]]
    assert any("job-1" in args for args in create_call_args)
