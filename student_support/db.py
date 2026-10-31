"""SQLite persistence. Every private read is explicitly scoped by its owner."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from flask import current_app, g
from werkzeug.security import generate_password_hash


def now():
    return datetime.now(timezone.utc).isoformat()


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"], timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    db = get_db()
    demo_password = current_app.config["DEMO_ACCOUNT_PASSWORD"]
    if not isinstance(demo_password, str) or len(demo_password) < 12:
        raise RuntimeError("Set DEMO_ACCOUNT_PASSWORD to a unique local value of at least 12 characters.")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS students (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, programme TEXT NOT NULL,
        email TEXT NOT NULL, password_hash TEXT NOT NULL,
        fee_total INTEGER, fee_paid INTEGER, fee_due TEXT,
        scholarship TEXT, scholarship_status TEXT, scholarship_amount INTEGER
    );
    CREATE TABLE IF NOT EXISTS memory (
        student_id TEXT NOT NULL REFERENCES students(id), key TEXT NOT NULL,
        value TEXT NOT NULL, updated_at TEXT NOT NULL,
        PRIMARY KEY(student_id,key)
    );
    CREATE TABLE IF NOT EXISTS tickets (
        id TEXT PRIMARY KEY, student_id TEXT NOT NULL REFERENCES students(id),
        category TEXT NOT NULL, description TEXT NOT NULL, status TEXT NOT NULL,
        created_at TEXT NOT NULL, run_id TEXT NOT NULL,
        UNIQUE(student_id,run_id,category,description)
    );
    CREATE TABLE IF NOT EXISTS approvals (
        id TEXT PRIMARY KEY, student_id TEXT NOT NULL REFERENCES students(id),
        field TEXT NOT NULL, old_value TEXT NOT NULL, new_value TEXT NOT NULL,
        status TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
        decided_at TEXT, run_id TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
        actor TEXT NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL,
        decision TEXT NOT NULL, approval_status TEXT, result TEXT NOT NULL, run_id TEXT
    );
    CREATE TABLE IF NOT EXISTS traces (
        id TEXT PRIMARY KEY, student_id TEXT NOT NULL REFERENCES students(id),
        created_at TEXT NOT NULL, data TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY, student_id TEXT NOT NULL REFERENCES students(id),
        title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL,
        trace_id TEXT, created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS conversations_by_student ON conversations(student_id, updated_at);
    CREATE INDEX IF NOT EXISTS messages_by_conversation ON messages(conversation_id, id);
    CREATE TABLE IF NOT EXISTS ticket_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT NOT NULL REFERENCES tickets(id),
        author_id TEXT NOT NULL, author_role TEXT NOT NULL CHECK(author_role IN ('student','staff')),
        body TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS notes_by_ticket ON ticket_notes(ticket_id, id);
    CREATE TABLE IF NOT EXISTS staff (
        id TEXT PRIMARY KEY, name TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('staff','admin')),
        email TEXT NOT NULL, password_hash TEXT NOT NULL
    );
    """)
    # Columns added after the first release; existing local databases are upgraded in place.
    add_columns(db, "tickets", (("updated_at", "TEXT"), ("staff_updated_at", "TEXT"), ("student_seen_at", "TEXT")))
    add_columns(db, "approvals", (("reviewed_by", "TEXT"), ("reviewed_at", "TEXT")))
    data = Path(current_app.root_path).parent / "data"
    for student in json.loads((data / "students.json").read_text()):
        db.execute("""INSERT OR IGNORE INTO students VALUES
            (:id,:name,:programme,:email,:password_hash,:fee_total,:fee_paid,:fee_due,
             :scholarship,:scholarship_status,:scholarship_amount)""",
            {**student, "password_hash": generate_password_hash(demo_password)})
    for member in json.loads((data / "staff.json").read_text()):
        db.execute("INSERT OR IGNORE INTO staff VALUES (:id,:name,:role,:email,:password_hash)",
                   {**member, "password_hash": generate_password_hash(demo_password)})
    db.commit()


def add_columns(db, table, columns):
    existing = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
    for name, declaration in columns:
        if name not in existing:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def audit(actor, action, target, decision, result, run_id=None, approval_status=None):
    # Metadata only. Never pass arbitrary model arguments, chat text or provider exceptions.
    get_db().execute("""INSERT INTO audit
        (timestamp,actor,action,target,decision,approval_status,result,run_id)
        VALUES (?,?,?,?,?,?,?,?)""",
        (now(), actor, action, target, decision, approval_status, result, run_id))


def rows(sql, args=()):
    return [dict(row) for row in get_db().execute(sql, args).fetchall()]
