from student_support.db import get_db, rows
from .conftest import TEST_PASSWORD, login
from .helpers import ScriptedProvider, tool_response


def staff_login(client, staff="STF001", role="staff", password=TEST_PASSWORD):
    csrf = client.get("/api/session").json["csrf_token"]
    return client.post("/api/staff/login", json={"staff_id": staff, "role": role, "password": password}, headers={"X-CSRF-Token": csrf})


def staff_headers(client, staff="STF001", role="staff"):
    result = staff_login(client, staff, role)
    assert result.status_code == 200
    return {"X-CSRF-Token": result.json["csrf_token"]}


def raise_ticket(app, client):
    headers = login(client)
    app.extensions["provider"] = ScriptedProvider([tool_response("create_support_request", {"category": "finance", "description": "Portal failed"}), "echo_tool"])
    client.post("/api/chat", json={"message": "Create a finance ticket"}, headers=headers)
    client.post("/api/logout", headers=headers)
    with app.app_context():
        return rows("SELECT id FROM tickets")[0]["id"]


def test_staff_and_admin_sign_in_with_matching_role(client):
    result = staff_login(client)
    assert result.status_code == 200 and result.json["staff"]["role"] == "staff" and result.json["student"] is None
    assert staff_login(client, "ADM001", "admin").json["staff"]["role"] == "admin"


def test_wrong_role_or_password_is_rejected_generically(client):
    for staff, role, password in [("STF001", "admin", TEST_PASSWORD), ("ADM001", "staff", TEST_PASSWORD),
                                  ("STF001", "staff", "wrong"), ("NOPE01", "staff", TEST_PASSWORD)]:
        result = staff_login(client, staff, role, password)
        assert result.status_code == 401
        assert result.json["error"] == "Staff ID, password or account type is incorrect."
    assert staff_login(client, "STF001", "superuser").status_code == 400


def test_students_cannot_sign_in_as_staff(client):
    assert staff_login(client, "STU001", "staff").status_code == 401


def test_staff_sees_and_updates_all_tickets(app, client):
    ticket_id = raise_ticket(app, client)
    headers = staff_headers(client)
    items = client.get("/api/staff/tickets").json["items"]
    assert items[0]["id"] == ticket_id and items[0]["student_name"] == "Demo Student One"
    assert client.post(f"/api/staff/tickets/{ticket_id}/status", json={"status": "in_progress"}, headers=headers).status_code == 200
    assert client.get("/api/staff/tickets?status=in_progress").json["items"][0]["id"] == ticket_id
    assert client.get("/api/staff/tickets?status=open").json["items"] == []
    with app.app_context():
        assert any(r["actor"] == "STF001" and r["result"] == "status_in_progress" for r in rows("SELECT * FROM audit"))
    login(client)
    assert client.get("/api/tickets").json["items"][0]["status"] == "in_progress"


def test_ticket_status_update_validated(app, client):
    ticket_id = raise_ticket(app, client)
    headers = staff_headers(client)
    assert client.post(f"/api/staff/tickets/{ticket_id}/status", json={"status": "deleted"}, headers=headers).status_code == 400
    assert client.post(f"/api/staff/tickets/{ticket_id}/status", json={"status": "resolved", "student_id": "STU002"}, headers=headers).status_code == 400
    assert client.post("/api/staff/tickets/NOPE/status", json={"status": "resolved"}, headers=headers).status_code == 404
    assert client.post(f"/api/staff/tickets/{ticket_id}/status", json={"status": "resolved"}).status_code == 403
    assert client.get("/api/staff/tickets?status=bogus").status_code == 400


def test_students_cannot_reach_staff_or_admin_routes(client, headers):
    assert client.get("/api/staff/tickets").status_code == 403
    assert client.get("/api/admin/audit").status_code == 403
    assert client.get("/api/admin/accounts").status_code == 403


def test_anonymous_cannot_reach_staff_routes(client):
    assert client.get("/api/staff/tickets").status_code == 401
    assert client.get("/api/admin/audit").status_code == 401


def test_staff_cannot_use_student_tools_or_admin_routes(client):
    headers = staff_headers(client)
    for path in ("/api/memory", "/api/traces", "/api/approvals", "/api/export"):
        assert client.get(path).status_code == 403
    assert client.post("/api/chat", json={"message": "fees"}, headers=headers).status_code == 403
    assert client.get("/api/admin/audit").status_code == 403
    assert client.get("/api/admin/accounts").status_code == 403


def test_admin_sees_accounts_without_hashes_and_full_audit(client):
    login(client)
    staff_headers(client, "ADM001", "admin")
    accounts = client.get("/api/admin/accounts").json
    assert {s["id"] for s in accounts["students"]} == {"STU001", "STU002"}
    assert {s["id"] for s in accounts["staff"]} == {"STF001", "ADM001"}
    assert "password_hash" not in str(accounts)
    actors = {r["actor"] for r in client.get("/api/admin/audit").json["items"]}
    assert {"STU001", "ADM001"} <= actors
    assert client.get("/api/staff/tickets").status_code == 200


def test_demoted_admin_loses_access_immediately(app, client):
    staff_headers(client, "ADM001", "admin")
    with app.app_context():
        get_db().execute("UPDATE staff SET role='staff' WHERE id='ADM001'")
        get_db().commit()
    assert client.get("/api/admin/audit").status_code == 403


def test_staff_reply_reaches_student_as_unread_update(app, client):
    ticket_id = raise_ticket(app, client)
    staff = app.test_client(); headers = staff_headers(staff)
    assert staff.post(f"/api/staff/tickets/{ticket_id}/notes", json={"body": "We are checking the portal logs."}, headers=headers).status_code == 200
    student_headers = login(client)
    assert client.get("/api/notifications").json["ticket_updates"] == 1
    ticket = client.get("/api/tickets").json["items"][0]
    assert ticket["unread"] and ticket["notes"][0]["author_name"] == "Demo Staff" and ticket["notes"][0]["author_role"] == "staff"
    client.post("/api/tickets/seen", headers=student_headers)
    assert client.get("/api/notifications").json["ticket_updates"] == 0
    assert client.post(f"/api/tickets/{ticket_id}/notes", json={"body": "Thanks, it failed at 9 pm."}, headers=student_headers).status_code == 200
    assert client.get("/api/notifications").json["ticket_updates"] == 0
    notes = staff.get("/api/staff/tickets").json["items"][0]["notes"]
    assert [n["author_role"] for n in notes] == ["staff", "student"] and notes[1]["author_name"] == "Demo Student One"


def test_status_change_is_an_unread_update(app, client):
    ticket_id = raise_ticket(app, client)
    staff = app.test_client(); headers = staff_headers(staff)
    staff.post(f"/api/staff/tickets/{ticket_id}/status", json={"status": "resolved"}, headers=headers)
    login(client)
    assert client.get("/api/notifications").json["ticket_updates"] == 1


def test_ticket_replies_validated_and_owner_scoped(app, client):
    ticket_id = raise_ticket(app, client)
    other_headers = login(client, "STU002")
    assert client.post(f"/api/tickets/{ticket_id}/notes", json={"body": "Not mine"}, headers=other_headers).status_code == 404
    assert client.get("/api/tickets").json["items"] == []
    owner_headers = login(client)
    for data in ({"body": ""}, {"body": "x" * 1001}, {"body": "ok", "author_role": "staff"}, {"body": "My OTP is 123456"}):
        assert client.post(f"/api/tickets/{ticket_id}/notes", json=data, headers=owner_headers).status_code == 400
    with app.app_context():
        assert rows("SELECT * FROM ticket_notes") == []


def test_staff_logout_clears_session(client):
    headers = staff_headers(client)
    assert client.post("/api/logout", headers=headers).status_code == 200
    assert client.get("/api/session").json["staff"] is None
    assert client.get("/api/staff/tickets").status_code == 401
