"""Rootdir conftest: pytest loads it before tests/conftest.py, so the test
isolation in tests/isolation.py is in place before any `app` module (and
app.config's module-level settings) is imported."""

import pytest

from tests import isolation

isolation.install()


def pytest_configure(config: pytest.Config) -> None:
    from app.config import Settings, settings

    problems = isolation.settings_problems(Settings, settings)
    if problems:
        raise pytest.UsageError(
            "API tests refuse to start outside isolation: "
            + "; ".join(problems)
            + ". Unset these variables in the shell (values are never shown)."
        )


@pytest.fixture(autouse=True)
def _fail_on_swallowed_isolation_breach():
    start = len(isolation.breaches)
    yield
    if len(isolation.breaches) > start:
        pytest.fail("Isolation breach: " + "; ".join(isolation.breaches[start:]), pytrace=False)
