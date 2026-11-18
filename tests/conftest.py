"""Общие фикстуры тестов: отдельная БД и TestClient."""
import os
from pathlib import Path

TEST_DB = Path(__file__).resolve().parent / "test_workshop.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["AUTO_SEED"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    if TEST_DB.exists():
        TEST_DB.unlink()
    with TestClient(app) as test_client:
        yield test_client
    engine.dispose()
    if TEST_DB.exists():
        TEST_DB.unlink()


@pytest.fixture
def anon(client):
    fresh = TestClient(app)
    yield fresh
    fresh.close()


def login(test_client: TestClient, email: str, password: str):
    test_client.get("/login")
    token = test_client.cookies.get("workshop_csrf")
    return test_client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


@pytest.fixture
def as_client(client):
    login(client, "client@workshop.ru", "client12345")
    return client


@pytest.fixture
def as_admin(client):
    login(client, "admin@workshop.ru", "admin12345")
    return client


@pytest.fixture
def as_master(client):
    login(client, "master@workshop.ru", "master12345")
    return client