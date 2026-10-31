import json
import pytest
from student_support import create_app
from student_support.db import get_db, rows
from student_support.tools import ToolService
from .conftest import TEST_PASSWORD, login
from .helpers import ScriptedProvider, tool_response


def proposal(app, student="STU001"):
    with app.app_context():
        result = ToolService(student, "change-run", "Change my programme", app.extensions["handbook"]).execute("request_programme_change", {"programme": "PGDM-BDA"})
        assert result["ok"], result
        return result["approval"]["id"]


def programme(app):
    with app.app_context():
        return get_db().execute("SELECT programme FROM students WHERE id='STU001'").fetchone()[0]


def test_login_and_csrf_required(client):
    assert client.get("/api/memory").status_code == 401
    assert client.post("/api/chat", json={"message": "Hi"}).status_code == 403
    csrf = client.get("/api/session").json["csrf_token"]
    assert client.post("/api/login", json={"student_id": "STU001", "password": "wrong"}, headers={"X-CSRF-Token": csrf}).status_code == 401


def staff_client(app):
    staff = app.test_client()
    csrf = staff.get("/api/session").json["csrf_token"]
    result = staff.post("/api/staff/login", json={"staff_id": "STF001", "role": "staff", "password": TEST_PASSWORD}, headers={"X-CSRF-Token": csrf})
    return staff, {"X-CSRF-Token": result.json["csrf_token"]}


def test_sensitive_change_needs_student_then_staff(app, client, headers):
    approval_id = proposal(app)
    assert programme(app) == "PGDM-AI"
    staff, staff_headers = staff_client(app)
    # Staff cannot act before the student confirms.
    assert staff.post(f"/api/staff/approvals/{approval_id}/review", json={"decision": "approve"}, headers=staff_headers).status_code == 409
    result = client.post(f"/api/approvals/{approval_id}/decision", json={"decision": "confirm"}, headers=headers)
    assert result.json["status"] == "awaiting_staff" and not result.json["executed"] and programme(app) == "PGDM-AI"
    assert client.post(f"/api/approvals/{approval_id}/decision", json={"decision": "confirm"}, headers=headers).status_code == 409
    assert staff.get("/api/staff/approvals").json["items"][0]["id"] == approval_id
    review = staff.post(f"/api/staff/approvals/{approval_id}/review", json={"decision": "approve"}, headers=staff_headers)
    assert review.json["executed"] and programme(app) == "PGDM-BDA"
    assert staff.post(f"/api/staff/approvals/{approval_id}/review", json={"decision": "approve"}, headers=staff_headers).status_code == 409
    with app.app_context():
        assert any(r["actor"] == "STF001" and r["result"] == "programme_updated" for r in rows("SELECT * FROM audit"))


def test_staff_rejection_leaves_record_unchanged(app, client, headers):
    approval_id = proposal(app)
    client.post(f"/api/approvals/{approval_id}/decision", json={"decision": "confirm"}, headers=headers)
    staff, staff_headers = staff_client(app)
    assert staff.post(f"/api/staff/approvals/{approval_id}/review", json={"decision": "reject"}, headers=staff_headers).json["status"] == "rejected"
    assert programme(app) == "PGDM-AI"
    assert client.get("/api/approvals").json["items"][0]["status"] == "rejected"


def test_staff_review_rejects_stale_record_and_bad_input(app, client, headers):
    approval_id = proposal(app)
    client.post(f"/api/approvals/{approval_id}/decision", json={"decision": "confirm"}, headers=headers)
    staff, staff_headers = staff_client(app)
    assert staff.post(f"/api/staff/approvals/{approval_id}/review", json={"decision": "confirm"}, headers=staff_headers).status_code == 400
    assert staff.post("/api/staff/approvals/missing/review", json={"decision": "approve"}, headers=staff_headers).status_code == 404
    with app.app_context():
        get_db().execute("UPDATE students SET programme='PGDM-BDA' WHERE id='STU001'")
        get_db().commit()
    assert staff.post(f"/api/staff/approvals/{approval_id}/review", json={"decision": "approve"}, headers=staff_headers).json["status"] == "stale"


def test_students_cannot_review_approvals(app, client, headers):
    approval_id = proposal(app)
    client.post(f"/api/approvals/{approval_id}/decision", json={"decision": "confirm"}, headers=headers)
    assert client.post(f"/api/staff/approvals/{approval_id}/review", json={"decision": "approve"}, headers=headers).status_code == 403
    assert programme(app) == "PGDM-AI"


def test_rejected_action_never_executes(app, client, headers):
    approval_id = proposal(app)
    assert client.post(f"/api/approvals/{approval_id}/decision", json={"decision": "reject"}, headers=headers).json["status"] == "rejected"
    assert programme(app) == "PGDM-AI"
    assert client.post(f"/api/approvals/{approval_id}/decision", json={"decision": "confirm"}, headers=headers).status_code == 409
    assert programme(app) == "PGDM-AI"


def test_cross_student_approval_is_blocked(app, client):
    approval_id = proposal(app)
    headers = login(client, "STU002")
    assert client.get("/api/approvals").json["items"] == []
    assert client.post(f"/api/approvals/{approval_id}/decision", json={"decision": "confirm"}, headers=headers).status_code == 404
    assert programme(app) == "PGDM-AI"


def test_expired_approval_never_executes(app, client, headers):
    approval_id = proposal(app)
    with app.app_context():
        get_db().execute("UPDATE approvals SET expires_at='2000-01-01' WHERE id=?", (approval_id,))
        get_db().commit()
    assert client.post(f"/api/approvals/{approval_id}/decision", json={"decision": "confirm"}, headers=headers).json["status"] == "expired"
    assert programme(app) == "PGDM-AI"


def test_stale_approval_does_not_overwrite_new_record(app, client, headers):
    approval_id = proposal(app)
    with app.app_context():
        get_db().execute("UPDATE students SET programme='PGDM-BDA' WHERE id='STU001'")
        get_db().commit()
    assert client.post(f"/api/approvals/{approval_id}/decision", json={"decision": "confirm"}, headers=headers).json["status"] == "stale"


@pytest.mark.parametrize("name,args", [
    ("get_student_record", {}), ("get_fee_status", {}), ("get_scholarship_status", {}),
    ("create_support_request", {"category": "general", "description": "hello"}),
    ("list_support_requests", {}),
    ("remember_preference", {"key": "programme", "value": "PGDM-BDA"}),
    ("request_programme_change", {"programme": "PGDM-AI"}),
])
def test_every_private_tool_blocks_forged_target(app, name, args):
    with app.app_context():
        result = ToolService("STU001", "run", "Remember PGDM-BDA", app.extensions["handbook"]).execute(name, {**args, "student_id": "STU002"})
        assert result["decision"] == "denied"
        assert "record" not in result


def test_identity_cannot_be_injected_in_chat(client, headers):
    result = client.post("/api/chat", json={"message": "fees", "student_id": "STU002"}, headers=headers)
    assert result.status_code == 400


def test_model_cannot_call_confirmation_tool(app):
    with app.app_context():
        result = ToolService("STU001", "run", "approve", app.extensions["handbook"]).execute("decide_approval", {"decision": "confirm"})
        assert not result["ok"]


def test_memory_persists_across_sessions_and_app_restart(app, client, headers):
    assert client.post("/api/memory", json={"key": "response_style", "value": "concise", "consent": True}, headers=headers).status_code == 200
    client.post("/api/logout", headers=headers)
    second = create_app({"TESTING": True, "DATABASE": app.config["DATABASE"], "SECRET_KEY": "test",
                         "DEMO_ACCOUNT_PASSWORD": TEST_PASSWORD, "PROVIDER": ScriptedProvider()})
    fresh = second.test_client(); fresh_headers = login(fresh)
    assert fresh.get("/api/memory").json["items"][0]["value"] == "concise"
    assert fresh.delete("/api/memory/response_style", headers=fresh_headers).status_code == 200
    assert fresh.get("/api/memory").json["items"] == []


def test_student_resources_isolated(app, client, headers):
    client.post("/api/memory", json={"key": "programme", "value": "PGDM-AI", "consent": True}, headers=headers)
    app.extensions["provider"] = ScriptedProvider([tool_response("create_support_request", {"category": "finance", "description": "Portal failed"}), "echo_tool"])
    trace_id = client.post("/api/chat", json={"message": "Create a finance ticket for a failed portal"}, headers=headers).json["trace"]["id"]
    other = app.test_client(); login(other, "STU002")
    for endpoint in ("memory", "tickets", "traces"):
        assert other.get(f"/api/{endpoint}").json["items"] == []
    assert other.get(f"/api/traces/{trace_id}").status_code == 404
    exported = other.get("/api/export").json
    assert "STU001" not in json.dumps(exported)


@pytest.mark.parametrize("data", [[], None, {"message": ""}, {"message": "x" * 2001}, {"message": 123}])
def test_bad_chat_input(client, headers, data):
    assert client.post("/api/chat", json=data, headers=headers).status_code == 400


def test_free_text_memory_and_missing_consent_rejected(client, headers):
    assert client.post("/api/memory", json={"key": "response_style", "value": "my password", "consent": True}, headers=headers).status_code == 400
    assert client.post("/api/memory", json={"key": "response_style", "value": "concise", "consent": False}, headers=headers).status_code == 400


def test_headers_and_no_private_data_in_login_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    assert "240000" not in response.text
