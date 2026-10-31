import sqlite3
from student_support import create_app
from .conftest import TEST_PASSWORD
from .helpers import ScriptedProvider


def test_existing_database_gains_new_columns(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE tickets (id TEXT PRIMARY KEY, student_id TEXT NOT NULL, category TEXT NOT NULL,
            description TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, run_id TEXT NOT NULL);
        CREATE TABLE approvals (id TEXT PRIMARY KEY, student_id TEXT NOT NULL, field TEXT NOT NULL,
            old_value TEXT NOT NULL, new_value TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL, decided_at TEXT, run_id TEXT NOT NULL);
        INSERT INTO tickets VALUES ('TKT-old','STU001','general','Old request','open','2026-01-01','run');
        """)
    app = create_app({"TESTING": True, "SECRET_KEY": "test", "DATABASE": str(path),
                      "DEMO_ACCOUNT_PASSWORD": TEST_PASSWORD, "PROVIDER": ScriptedProvider()})
    with sqlite3.connect(path) as db:
        assert {"updated_at", "staff_updated_at", "student_seen_at"} <= {r[1] for r in db.execute("PRAGMA table_info(tickets)")}
        assert {"reviewed_by", "reviewed_at"} <= {r[1] for r in db.execute("PRAGMA table_info(approvals)")}
    client = app.test_client()
    csrf = client.get("/api/session").json["csrf_token"]
    client.post("/api/login", json={"student_id": "STU001", "password": TEST_PASSWORD}, headers={"X-CSRF-Token": csrf})
    ticket = client.get("/api/tickets").json["items"][0]
    assert ticket["id"] == "TKT-old" and ticket["updated_at"] == "2026-01-01" and not ticket["unread"]
