from student_support import create_app
from student_support.db import rows
from .conftest import TEST_PASSWORD, login
from .helpers import ScriptedProvider, answer_response


def chat(app, client, headers, text, answer="Done."):
    app.extensions["provider"] = ScriptedProvider([answer_response(answer)])
    response = client.post("/api/chat", json={"message": text}, headers=headers)
    assert response.status_code == 200
    return response.json


def test_conversation_saved_and_listed(app, client, headers):
    first = chat(app, client, headers, "What is my scholarship status?", "Your status is **under review**.")
    chat(app, client, headers, "And the amount?", "It is **₹0**.")
    items = client.get("/api/conversations").json["items"]
    assert len(items) == 1 and items[0]["id"] == first["conversation_id"]
    assert items[0]["title"] == "What is my scholarship status?"
    opened = client.post(f"/api/conversations/{first['conversation_id']}/open", headers=headers).json
    assert [m["role"] for m in opened["messages"]] == ["user", "assistant", "user", "assistant"]
    assert opened["messages"][3]["content"] == "It is **₹0**."
    assert opened["messages"][1]["trace"]["id"] == first["trace"]["id"]


def test_new_conversation_starts_separate_history(app, client, headers):
    chat(app, client, headers, "First chat")
    client.post("/api/conversation/new", headers=headers)
    chat(app, client, headers, "Second chat")
    assert [c["title"] for c in client.get("/api/conversations").json["items"]] == ["Second chat", "First chat"]


def test_history_survives_sign_out_and_restart(app, client, headers):
    conversation_id = chat(app, client, headers, "Remember this chat")["conversation_id"]
    client.post("/api/logout", headers=headers)
    second = create_app({"TESTING": True, "DATABASE": app.config["DATABASE"], "SECRET_KEY": "test",
                         "DEMO_ACCOUNT_PASSWORD": TEST_PASSWORD, "PROVIDER": ScriptedProvider()})
    fresh = second.test_client(); fresh_headers = login(fresh)
    assert fresh.get("/api/conversations").json["items"][0]["id"] == conversation_id
    assert fresh.post(f"/api/conversations/{conversation_id}/open", headers=fresh_headers).json["messages"][0]["content"] == "Remember this chat"


def test_reopened_conversation_restores_followup_context(app, client, headers):
    conversation_id = chat(app, client, headers, "Create a support request", "Which issue should I report?")["conversation_id"]
    client.post("/api/conversation/new", headers=headers)
    client.post(f"/api/conversations/{conversation_id}/open", headers=headers)
    assert chat(app, client, headers, "Payment portal failed")["trace"]["context"]["history_messages"] == 2


def test_sensitive_message_text_is_not_stored(app, client, headers):
    chat(app, client, headers, "My OTP is 123456")
    with app.app_context():
        stored = rows("SELECT content FROM messages") + rows("SELECT title AS content FROM conversations")
    assert stored and all("123456" not in m["content"] for m in stored)


def test_history_is_private_to_each_student(app, client, headers):
    conversation_id = chat(app, client, headers, "Private question")["conversation_id"]
    other = app.test_client(); other_headers = login(other, "STU002")
    assert other.get("/api/conversations").json["items"] == []
    assert other.post(f"/api/conversations/{conversation_id}/open", headers=other_headers).status_code == 404
    assert other.delete(f"/api/conversations/{conversation_id}", headers=other_headers).status_code == 404
    assert "Private question" not in str(other.get("/api/export").json)
    assert "Private question" in str(client.get("/api/export").json)


def test_delete_conversation_removes_messages(app, client, headers):
    conversation_id = chat(app, client, headers, "Delete me")["conversation_id"]
    assert client.delete(f"/api/conversations/{conversation_id}", headers=headers).status_code == 200
    assert client.get("/api/conversations").json["items"] == []
    with app.app_context():
        assert rows("SELECT * FROM messages") == []
        assert any(r["action"] == "delete_conversation" for r in rows("SELECT * FROM audit"))


def test_staff_cannot_read_student_history(app, client, headers):
    conversation_id = chat(app, client, headers, "Private question")["conversation_id"]
    staff = app.test_client()
    csrf = staff.get("/api/session").json["csrf_token"]
    signed_in = staff.post("/api/staff/login", json={"staff_id": "ADM001", "role": "admin", "password": TEST_PASSWORD}, headers={"X-CSRF-Token": csrf})
    staff_headers = {"X-CSRF-Token": signed_in.json["csrf_token"]}
    assert staff.get("/api/conversations").status_code == 403
    assert staff.post(f"/api/conversations/{conversation_id}/open", headers=staff_headers).status_code == 403
