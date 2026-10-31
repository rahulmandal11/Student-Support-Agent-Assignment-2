import pytest
from student_support import create_app
from .helpers import ScriptedProvider

TEST_PASSWORD = "test-only-password"


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING": True, "SECRET_KEY": "test-only-secret", "DATABASE": str(tmp_path / "test.db"),
                       "GROQ_API_KEY": "", "DEMO_ACCOUNT_PASSWORD": TEST_PASSWORD,
                       "PROVIDER": ScriptedProvider()})


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, student="STU001"):
    csrf = client.get("/api/session").json["csrf_token"]
    result = client.post("/api/login", json={"student_id": student, "password": TEST_PASSWORD}, headers={"X-CSRF-Token": csrf})
    assert result.status_code == 200
    return {"X-CSRF-Token": result.json["csrf_token"]}


@pytest.fixture
def headers(client):
    return login(client)
