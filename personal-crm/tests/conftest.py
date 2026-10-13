import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from personal_crm.adapters import FixtureInterpreter
from personal_crm.db import sessions
from personal_crm.service import CRMService


@pytest.fixture(scope="session")
def factory():
    url = os.getenv("CRM_TEST_DATABASE_URL", "")
    if not url or not url.rsplit("/", 1)[-1].startswith("personal_crm_test"):
        pytest.fail("Set CRM_TEST_DATABASE_URL to a disposable personal_crm_test* PostgreSQL database")
    factory = sessions(url)
    # The opt-in database name and variable guard against destructive production resets.
    with factory.begin() as s:
        s.execute(text("DROP SCHEMA public CASCADE"))
        s.execute(text("CREATE SCHEMA public"))
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                   env={**os.environ, "CRM_DATABASE_URL": url}, check=True)
    return factory


@pytest.fixture(autouse=True)
def clean(request):
    if "factory" not in request.fixturenames:
        return
    factory = request.getfixturevalue("factory")
    with factory.begin() as s:
        s.execute(text("TRUNCATE profiles CASCADE"))


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 13, 8, tzinfo=UTC)

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def interpreter():
    return FixtureInterpreter({
        "synthetic task": {"operation": "create", "title": "Synthetic task", "obvious": True},
        "synthetic wait": {"operation": "create", "kind": "waiting", "title": "Wait for synthetic file", "obvious": True},
    })


@pytest.fixture
def service(factory, interpreter, clock):
    service = CRMService(factory, interpreter, clock)
    service.register("synthetic-owner", "Europe/Berlin")
    return service
