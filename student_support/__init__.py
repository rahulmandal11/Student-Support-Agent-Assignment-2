import json
import os
import secrets
import threading
import time
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, session
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash

from .agent import run_agent
from .context import ConversationContext
from .db import audit, close_db, get_db, init_db, now, rows
from .privacy import MEMORY_VALUES, sensitive
from .provider import GroqProvider
from .retrieval import Handbook
from .tools import decide_approval, review_approval

PUBLIC_PATHS = ("/api/session", "/api/login", "/api/staff/login")
TICKET_STATUSES = ("open", "in_progress", "resolved")
HIDDEN_MESSAGE = "Message hidden: it contained sensitive information, so it was not sent or saved."


def create_app(test_config=None):
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")
    app = Flask(__name__, instance_path=str(root / "instance"))
    Path(app.instance_path).mkdir(exist_ok=True)
    secret = os.getenv("SECRET_KEY")
    if not secret:
        secret_file = Path(app.instance_path) / "session.key"
        try:
            with secret_file.open("x", encoding="utf-8") as f:
                f.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        secret = secret_file.read_text(encoding="utf-8").strip()
    app.config.update(SECRET_KEY=secret, DATABASE=str(root / "instance/campus.db"),
                      GROQ_API_KEY=os.getenv("GROQ_API_KEY", ""),
                      GROQ_MODEL=os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
                      DEMO_ACCOUNT_PASSWORD=os.getenv("DEMO_ACCOUNT_PASSWORD", ""),
                      ASSIGNMENT_PROFILE=os.getenv("ASSIGNMENT_PROFILE", "a2").lower(),
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "false").lower() == "true",
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=2), MAX_CONTENT_LENGTH=16_384)
    if test_config:
        app.config.update(test_config)
    if app.config["ASSIGNMENT_PROFILE"] not in ("a1", "a2"):
        raise ValueError("ASSIGNMENT_PROFILE must be either 'a1' or 'a2'.")
    app.teardown_appcontext(close_db)
    app.extensions["handbook"] = Handbook()
    app.extensions["provider"] = app.config.get("PROVIDER") or GroqProvider(app.config["GROQ_API_KEY"], app.config["GROQ_MODEL"])
    app.extensions["chat_locks"] = {}
    app.extensions["login_attempts"] = {}
    app.extensions["conversation_context"] = ConversationContext()
    with app.app_context():
        init_db()

    @app.before_request
    def protect():
        if request.path.startswith("/api/"):
            session.setdefault("csrf", secrets.token_urlsafe(32))
            if request.method in ("POST", "PUT", "PATCH", "DELETE"):
                if not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), session["csrf"]):
                    return jsonify(error="Your session token expired. Refresh the page and try again."), 403
            if request.path in PUBLIC_PATHS:
                return None
            if request.path == "/api/logout":
                if not session.get("student_id") and not session.get("staff_id"):
                    return jsonify(error="Please sign in first."), 401
            elif request.path.startswith(("/api/staff/", "/api/admin/")):
                # Role is re-read from the database so a demoted account loses access immediately.
                member = current_staff()
                if not member and session.get("student_id"):
                    return jsonify(error="This area is for staff accounts only."), 403
                if not member:
                    return jsonify(error="Please sign in first."), 401
                if request.path.startswith("/api/admin/") and member["role"] != "admin":
                    return jsonify(error="This area is for administrators only."), 403
            elif not session.get("student_id"):
                if session.get("staff_id"):
                    return jsonify(error="Staff accounts cannot use the student assistant."), 403
                return jsonify(error="Please sign in first."), 401

    @app.after_request
    def security_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.errorhandler(500)
    def internal_error(_error):
        return jsonify(error="The request could not be completed. Please try again."), 500

    def body():
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else {}

    def actor():
        return session["student_id"]

    def current_staff():
        if not session.get("staff_id"):
            return None
        record = get_db().execute("SELECT id,name,role,email FROM staff WHERE id=?", (session["staff_id"],)).fetchone()
        return dict(record) if record else None

    def throttled():
        identity = request.remote_addr or "local"
        attempts = app.extensions["login_attempts"]
        recent = [t for t in attempts.get(identity, []) if time.monotonic() - t < 60]
        attempts[identity] = recent
        if len(recent) >= 10:
            return True
        recent.append(time.monotonic())
        return False

    def start_session(**identity):
        app.extensions["conversation_context"].clear(session.get("conversation_id"))
        session.clear()
        session.update(**identity, csrf=secrets.token_urlsafe(32), conversation_id=secrets.token_urlsafe(24))
        session.permanent = True

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/session")
    def session_info():
        student = None
        if session.get("student_id"):
            record = get_db().execute("SELECT id,name,programme,email FROM students WHERE id=?", (actor(),)).fetchone()
            student = dict(record) if record else None
        return jsonify(student=student, staff=current_staff(), csrf_token=session["csrf"], configured=bool(app.config["GROQ_API_KEY"]),
                       model=app.config["GROQ_MODEL"], memory_options=MEMORY_VALUES)

    @app.post("/api/login")
    def login():
        data = body()
        student_id, password = data.get("student_id"), data.get("password")
        if not isinstance(student_id, str) or not isinstance(password, str) or len(password) > 200:
            return jsonify(error="Enter a student ID and password."), 400
        if throttled():
            return jsonify(error="Too many sign-in attempts. Try again in a minute."), 429
        student = get_db().execute("SELECT id,password_hash FROM students WHERE id=?", (student_id.upper(),)).fetchone()
        if not student or not check_password_hash(student["password_hash"], password):
            audit("anonymous", "login", "student_account", "denied", "invalid_credentials")
            get_db().commit()
            return jsonify(error="Student ID or password is incorrect."), 401
        start_session(student_id=student["id"])
        audit(student["id"], "login", student["id"], "allowed", "signed_in")
        get_db().commit()
        return session_info()

    @app.post("/api/staff/login")
    def staff_login():
        data = body()
        staff_id, password, role = data.get("staff_id"), data.get("password"), data.get("role")
        if not isinstance(staff_id, str) or not isinstance(password, str) or len(password) > 200 or role not in ("staff", "admin"):
            return jsonify(error="Enter a staff ID and password."), 400
        if throttled():
            return jsonify(error="Too many sign-in attempts. Try again in a minute."), 429
        member = get_db().execute("SELECT id,role,password_hash FROM staff WHERE id=?", (staff_id.upper(),)).fetchone()
        # One generic message for unknown ID, wrong password and wrong role, so accounts can't be enumerated.
        if not member or not check_password_hash(member["password_hash"], password) or member["role"] != role:
            audit("anonymous", "staff_login", "staff_account", "denied", "invalid_credentials")
            get_db().commit()
            return jsonify(error="Staff ID, password or account type is incorrect."), 401
        start_session(staff_id=member["id"])
        audit(member["id"], "staff_login", member["id"], "allowed", f"signed_in_as_{member['role']}")
        get_db().commit()
        return session_info()

    @app.post("/api/logout")
    def logout():
        who = session.get("student_id") or session["staff_id"]
        audit(who, "logout", who, "allowed", "signed_out")
        get_db().commit()
        app.extensions["conversation_context"].clear(session.get("conversation_id"))
        session.clear()
        return jsonify(ok=True)

    @app.post("/api/conversation/new")
    def new_conversation():
        app.extensions["conversation_context"].clear(session.get("conversation_id"))
        session["conversation_id"] = secrets.token_urlsafe(24)
        return jsonify(ok=True)

    @app.post("/api/chat")
    def chat():
        data = body()
        question = data.get("message")
        if not isinstance(question, str) or not question.strip() or len(question) > 2000:
            return jsonify(error="Enter a question between 1 and 2000 characters."), 400
        if set(data) != {"message"}:
            return jsonify(error="Unexpected request fields. Identity is set by your signed-in session."), 400
        lock = app.extensions["chat_locks"].setdefault(actor(), threading.Lock())
        if not lock.acquire(blocking=False):
            return jsonify(error="A response is already in progress. Please wait."), 409
        try:
            conversation_id = session.setdefault("conversation_id", secrets.token_urlsafe(24))
            context = app.extensions["conversation_context"]
            recent = context.select(conversation_id, question)
            result = run_agent(actor(), question.strip(), app.extensions["provider"], app.extensions["handbook"],
                               profile=app.config["ASSIGNMENT_PROFILE"], recent_context=recent)
            if result["trace"]["status"] == "completed":
                context.remember_exchange(conversation_id, question, result["answer"])
            save_exchange(conversation_id, question.strip(), result)
            return jsonify({**result, "conversation_id": conversation_id})
        finally:
            lock.release()

    def save_exchange(conversation_id, question, result):
        # Sensitive messages are blocked before the model, so their text is never written to history either.
        filtered = result["trace"]["status"] == "privacy_filtered"
        text = HIDDEN_MESSAGE if filtered else question
        db, stamp = get_db(), now()
        owner = db.execute("SELECT student_id FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if owner and owner["student_id"] != actor():
            return
        if owner:
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (stamp, conversation_id))
        else:
            title = "Sensitive message" if filtered else (question if len(question) <= 60 else question[:57] + "…")
            db.execute("INSERT INTO conversations VALUES (?,?,?,?,?)", (conversation_id, actor(), title, stamp, stamp))
        db.executemany("INSERT INTO messages (conversation_id,role,content,trace_id,created_at) VALUES (?,?,?,?,?)",
                       [(conversation_id, "user", text, None, stamp),
                        (conversation_id, "assistant", result["answer"], result["trace"]["id"], stamp)])
        db.commit()

    def owned_conversation(conversation_id):
        record = get_db().execute("SELECT id,title,created_at,updated_at FROM conversations WHERE id=? AND student_id=?",
                                  (conversation_id, actor())).fetchone()
        return dict(record) if record else None

    def conversation_messages(conversation_id):
        items = rows("""SELECT m.role,m.content,m.created_at,t.data AS trace FROM messages m
                        LEFT JOIN traces t ON t.id=m.trace_id AND t.student_id=?
                        WHERE m.conversation_id=? ORDER BY m.id""", (actor(), conversation_id))
        for item in items:
            item["trace"] = json.loads(item["trace"]) if item["trace"] else None
        return items

    @app.get("/api/conversations")
    def conversation_list():
        return jsonify(items=rows("SELECT id,title,updated_at FROM conversations WHERE student_id=? ORDER BY updated_at DESC LIMIT 100", (actor(),)),
                       current=session.get("conversation_id"))

    @app.post("/api/conversations/<conversation_id>/open")
    def conversation_open(conversation_id):
        record = owned_conversation(conversation_id)
        if not record:
            return jsonify(error="Conversation not found."), 404
        messages = conversation_messages(conversation_id)
        context = app.extensions["conversation_context"]
        context.clear(session.get("conversation_id"))
        session["conversation_id"] = conversation_id
        # Resume with the last exchange as temporary context, as if it had just happened.
        if len(messages) >= 2 and messages[-2]["role"] == "user" and messages[-2]["content"] != HIDDEN_MESSAGE:
            context.remember_exchange(conversation_id, messages[-2]["content"], messages[-1]["content"])
        return jsonify(conversation=record, messages=messages)

    @app.delete("/api/conversations/<conversation_id>")
    def conversation_delete(conversation_id):
        if not owned_conversation(conversation_id):
            return jsonify(error="Conversation not found."), 404
        get_db().execute("DELETE FROM messages WHERE conversation_id=?", (conversation_id,))
        get_db().execute("DELETE FROM conversations WHERE id=? AND student_id=?", (conversation_id, actor()))
        audit(actor(), "delete_conversation", actor(), "allowed", "chat_history_deleted")
        get_db().commit()
        if session.get("conversation_id") == conversation_id:
            app.extensions["conversation_context"].clear(conversation_id)
            session["conversation_id"] = secrets.token_urlsafe(24)
        return jsonify(ok=True)

    @app.get("/api/profile")
    def profile():
        record = get_db().execute("""SELECT id,name,programme,email,fee_total,fee_paid,fee_due,
            scholarship,scholarship_status,scholarship_amount FROM students WHERE id=?""", (actor(),)).fetchone()
        count = lambda sql, *args: get_db().execute(sql, (actor(), *args)).fetchone()[0]
        stats = {"conversations": count("SELECT COUNT(*) FROM conversations WHERE student_id=?"),
                 "open_tickets": count("SELECT COUNT(*) FROM tickets WHERE student_id=? AND status!='resolved'"),
                 "pending_approvals": count("SELECT COUNT(*) FROM approvals WHERE student_id=? AND status='pending' AND expires_at>?", now()),
                 "preferences": count("SELECT COUNT(*) FROM memory WHERE student_id=?")}
        return jsonify(profile=dict(record), stats=stats)

    @app.get("/api/memory")
    def memory_list():
        return jsonify(items=rows("SELECT key,value,updated_at FROM memory WHERE student_id=? ORDER BY key", (actor(),)))

    @app.post("/api/memory")
    def memory_save():
        data = body()
        key, value = data.get("key"), data.get("value")
        if not isinstance(key, str) or key not in MEMORY_VALUES or value not in MEMORY_VALUES[key] or data.get("consent") is not True or set(data) != {"key", "value", "consent"}:
            return jsonify(error="Select an allowed preference and explicitly agree to remember it."), 400
        get_db().execute("INSERT INTO memory VALUES (?,?,?,?) ON CONFLICT(student_id,key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at", (actor(), key, value, now()))
        audit(actor(), "save_memory", actor(), "allowed", "explicit_preference_saved")
        get_db().commit()
        return memory_list()

    @app.delete("/api/memory/<key>")
    def memory_delete(key):
        get_db().execute("DELETE FROM memory WHERE student_id=? AND key=?", (actor(), key))
        audit(actor(), "delete_memory", actor(), "allowed", "preference_deleted")
        get_db().commit()
        return jsonify(ok=True)

    @app.get("/api/approvals")
    def approvals_list():
        return jsonify(items=rows("SELECT * FROM approvals WHERE student_id=? ORDER BY created_at DESC LIMIT 50", (actor(),)))

    @app.post("/api/approvals/<approval_id>/decision")
    def approval_decision(approval_id):
        data = body()
        if data.get("decision") not in ("confirm", "reject") or set(data) != {"decision"}:
            return jsonify(error="Choose confirm or reject."), 400
        result, status = decide_approval(actor(), approval_id, data["decision"])
        return jsonify(result), status

    def with_notes(tickets):
        ids = [t["id"] for t in tickets]
        notes = rows(f"""SELECT n.ticket_id,n.author_role,COALESCE(st.name,su.name,n.author_id) AS author_name,n.body,n.created_at
                         FROM ticket_notes n
                         LEFT JOIN staff st ON st.id=n.author_id AND n.author_role='staff'
                         LEFT JOIN students su ON su.id=n.author_id AND n.author_role='student'
                         WHERE n.ticket_id IN ({','.join('?' * len(ids))}) ORDER BY n.id""", ids) if ids else []
        grouped = {}
        for note in notes:
            grouped.setdefault(note.pop("ticket_id"), []).append(note)
        for ticket in tickets:
            ticket["notes"] = grouped.get(ticket["id"], [])
        return tickets

    def note_text(data):
        text = data.get("body")
        if set(data) != {"body"} or not isinstance(text, str) or not text.strip() or len(text) > 1000:
            return None, "Write a reply between 1 and 1000 characters."
        if sensitive(text):
            return None, "Remove passwords, OTPs, card, bank or health details before sending."
        return text.strip(), None

    def add_note(ticket_id, author_id, role, text):
        stamp = now()
        get_db().execute("INSERT INTO ticket_notes (ticket_id,author_id,author_role,body,created_at) VALUES (?,?,?,?,?)",
                         (ticket_id, author_id, role, text, stamp))
        if role == "staff":
            get_db().execute("UPDATE tickets SET updated_at=?,staff_updated_at=? WHERE id=?", (stamp, stamp, ticket_id))
        else:
            get_db().execute("UPDATE tickets SET updated_at=?,student_seen_at=? WHERE id=?", (stamp, stamp, ticket_id))
        audit(author_id, "reply_ticket", ticket_id, "allowed", f"{role}_reply_added")
        get_db().commit()

    UNREAD = "(staff_updated_at IS NOT NULL AND (student_seen_at IS NULL OR staff_updated_at>student_seen_at))"

    @app.get("/api/tickets")
    def ticket_list():
        return jsonify(items=with_notes(rows(f"""SELECT id,category,description,status,created_at,
            COALESCE(updated_at,created_at) AS updated_at,{UNREAD} AS unread FROM tickets WHERE student_id=?
            ORDER BY COALESCE(updated_at,created_at) DESC LIMIT 100""", (actor(),))))

    @app.post("/api/tickets/seen")
    def tickets_seen():
        get_db().execute("UPDATE tickets SET student_seen_at=? WHERE student_id=?", (now(), actor()))
        get_db().commit()
        return jsonify(ok=True)

    @app.post("/api/tickets/<ticket_id>/notes")
    def ticket_reply(ticket_id):
        if not get_db().execute("SELECT 1 FROM tickets WHERE id=? AND student_id=?", (ticket_id, actor())).fetchone():
            return jsonify(error="Ticket not found."), 404
        text, error = note_text(body())
        if error:
            return jsonify(error=error), 400
        add_note(ticket_id, actor(), "student", text)
        return jsonify(ok=True)

    @app.get("/api/notifications")
    def notifications():
        db = get_db()
        return jsonify(pending_approvals=db.execute("SELECT COUNT(*) FROM approvals WHERE student_id=? AND status='pending' AND expires_at>?", (actor(), now())).fetchone()[0],
                       ticket_updates=db.execute(f"SELECT COUNT(*) FROM tickets WHERE student_id=? AND {UNREAD}", (actor(),)).fetchone()[0])

    @app.get("/api/audit")
    def audit_list():
        return jsonify(items=rows("SELECT * FROM audit WHERE actor=? ORDER BY id DESC LIMIT 200", (actor(),)))

    @app.get("/api/traces")
    def trace_list():
        return jsonify(items=[json.loads(r["data"]) for r in rows("SELECT data FROM traces WHERE student_id=? ORDER BY created_at DESC LIMIT 50", (actor(),))])

    @app.get("/api/traces/<trace_id>")
    def trace_get(trace_id):
        record = get_db().execute("SELECT data FROM traces WHERE id=? AND student_id=?", (trace_id, actor())).fetchone()
        if not record:
            return jsonify(error="Trace not found."), 404
        return jsonify(json.loads(record["data"]))

    @app.get("/api/export")
    def export():
        payload = {"student_id": actor(), "exported_at": now(),
                   "conversations": [{**c, "messages": [{k: m[k] for k in ("role", "content", "created_at")} for m in conversation_messages(c["id"])]}
                                     for c in rows("SELECT id,title,created_at,updated_at FROM conversations WHERE student_id=? ORDER BY created_at", (actor(),))],
                   "traces": [json.loads(r["data"]) for r in rows("SELECT data FROM traces WHERE student_id=? ORDER BY created_at", (actor(),))],
                   "audit": rows("SELECT * FROM audit WHERE actor=? ORDER BY id", (actor(),))}
        response = jsonify(payload)
        response.headers["Content-Disposition"] = 'attachment; filename="campus-desk-evidence.json"'
        return response

    # Staff see support requests and confirmed programme changes only. Chats, traces, memory and fees stay private.
    @app.get("/api/staff/tickets")
    def staff_ticket_list():
        status = request.args.get("status")
        if status and status not in TICKET_STATUSES:
            return jsonify(error="Unknown ticket status."), 400
        sql = """SELECT t.id,t.student_id,s.name AS student_name,t.category,t.description,t.status,t.created_at,
                 COALESCE(t.updated_at,t.created_at) AS updated_at FROM tickets t JOIN students s ON s.id=t.student_id"""
        args = ()
        if status:
            sql, args = sql + " WHERE t.status=?", (status,)
        return jsonify(items=with_notes(rows(sql + " ORDER BY COALESCE(t.updated_at,t.created_at) DESC LIMIT 200", args)), statuses=TICKET_STATUSES)

    @app.post("/api/staff/tickets/<ticket_id>/status")
    def staff_ticket_status(ticket_id):
        data = body()
        if data.get("status") not in TICKET_STATUSES or set(data) != {"status"}:
            return jsonify(error="Choose open, in_progress or resolved."), 400
        stamp = now()
        updated = get_db().execute("UPDATE tickets SET status=?,updated_at=?,staff_updated_at=? WHERE id=?", (data["status"], stamp, stamp, ticket_id)).rowcount
        if not updated:
            return jsonify(error="Ticket not found."), 404
        audit(session["staff_id"], "update_ticket", ticket_id, "allowed", f"status_{data['status']}")
        get_db().commit()
        return jsonify(ok=True, status=data["status"])

    @app.post("/api/staff/tickets/<ticket_id>/notes")
    def staff_ticket_reply(ticket_id):
        if not get_db().execute("SELECT 1 FROM tickets WHERE id=?", (ticket_id,)).fetchone():
            return jsonify(error="Ticket not found."), 404
        text, error = note_text(body())
        if error:
            return jsonify(error=error), 400
        add_note(ticket_id, session["staff_id"], "staff", text)
        return jsonify(ok=True)

    @app.get("/api/staff/approvals")
    def staff_approval_list():
        status = request.args.get("status", "awaiting_staff")
        if status not in ("awaiting_staff", "approved", "rejected", "stale", "all"):
            return jsonify(error="Unknown approval status."), 400
        sql = """SELECT a.id,a.student_id,s.name AS student_name,a.field,a.old_value,a.new_value,a.status,
                 a.created_at,a.decided_at,a.reviewed_by,a.reviewed_at FROM approvals a JOIN students s ON s.id=a.student_id"""
        # Requests the student has not confirmed yet are not staff business.
        sql, args = (sql + " WHERE a.status=?", (status,)) if status != "all" else (sql + " WHERE a.decided_at IS NOT NULL AND a.status!='expired'", ())
        return jsonify(items=rows(sql + " ORDER BY COALESCE(a.reviewed_at,a.decided_at) DESC LIMIT 200", args))

    @app.post("/api/staff/approvals/<approval_id>/review")
    def staff_approval_review(approval_id):
        data = body()
        if data.get("decision") not in ("approve", "reject") or set(data) != {"decision"}:
            return jsonify(error="Choose approve or reject."), 400
        result, status = review_approval(session["staff_id"], approval_id, data["decision"])
        return jsonify(result), status

    @app.get("/api/admin/accounts")
    def admin_accounts():
        return jsonify(students=rows("SELECT id,name,programme,email FROM students ORDER BY id"),
                       staff=rows("SELECT id,name,role,email FROM staff ORDER BY id"))

    @app.get("/api/admin/audit")
    def admin_audit():
        return jsonify(items=rows("SELECT * FROM audit ORDER BY id DESC LIMIT 500"))

    return app
