from .conftest import TEST_PASSWORD, login
from .helpers import ScriptedProvider, answer_response


def test_assignment_2_profile_includes_programme_change_tool(app, client, headers):
    provider = ScriptedProvider([answer_response("Hello.")])
    app.extensions["provider"] = provider
    response = client.post("/api/chat", json={"message": "Hello"}, headers=headers)
    assert response.status_code == 200
    assert response.json["trace"]["profile"] == "a2"
    names = [tool["function"]["name"] for tool in provider.tool_definitions[0]]
    assert "request_programme_change" in names


def test_profile_shows_own_record_and_activity(app, client, headers):
    client.post("/api/memory", json={"key": "response_style", "value": "concise", "consent": True}, headers=headers)
    app.extensions["provider"] = ScriptedProvider([answer_response("Hello.")])
    client.post("/api/chat", json={"message": "Hi"}, headers=headers)
    data = client.get("/api/profile").json
    assert data["profile"]["id"] == "STU001" and data["profile"]["fee_total"] == 240000
    assert "password_hash" not in data["profile"]
    assert data["stats"] == {"conversations": 1, "open_tickets": 0, "pending_approvals": 0, "preferences": 1}


def test_profile_is_scoped_to_signed_in_student(client):
    login(client, "STU002")
    assert client.get("/api/profile").json["profile"]["name"] == "Demo Student Two"


def test_profile_requires_student_session(client):
    assert client.get("/api/profile").status_code == 401
    csrf = client.get("/api/session").json["csrf_token"]
    client.post("/api/staff/login", json={"staff_id": "STF001", "role": "staff", "password": TEST_PASSWORD}, headers={"X-CSRF-Token": csrf})
    assert client.get("/api/profile").status_code == 403
