import json
import uuid
from datetime import datetime, timedelta, timezone

from .db import audit, get_db, now, rows
from .privacy import MEMORY_VALUES, memory_consent, sensitive


def definition(name, description, properties=None, required=None, private=False):
    properties = dict(properties or {})
    if private:
        properties["student_id"] = {"type": "string", "description": "Optional requested student ID. Only the signed-in student's ID is allowed."}
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties,
                           "required": required or [], "additionalProperties": False}}}


TEXT = {"type": "string"}
DEFINITIONS = [
    definition("get_student_record", "Read the signed-in student's name, programme and email.", private=True),
    definition("get_fee_status", "Read actual fees, payments, outstanding balance and due date. Always use for personal fee questions.", private=True),
    definition("get_scholarship_status", "Read the signed-in student's recorded scholarship status and amount.", private=True),
    definition("search_policy", "Retrieve relevant handbook excerpts. Use for policy questions; cite chunk IDs. Empty results mean the handbook does not answer the question.", {"query": TEXT}, ["query"]),
    definition("create_support_request", "Create a LOCAL DEMO ticket when the student explicitly requests it. It appears in the demo staff console; no email is sent and no response time is promised. Ask for missing category or description. Never include secrets.",
               {"category": {"type": "string", "enum": ["finance", "scholarship", "academic", "general"]}, "description": TEXT}, ["category", "description"], True),
    definition("list_support_requests", "List the signed-in student's support tickets.", private=True),
    definition("remember_preference", "Remember an explicitly requested safe fact only. The user must say remember/save and provide the exact allowed value.",
               {"key": {"type": "string", "enum": list(MEMORY_VALUES)}, "value": TEXT}, ["key", "value"], True),
    definition("request_programme_change", "Propose a sensitive programme change. Returns pending approval; does NOT change the record. The student must confirm using the app button, then Student Services staff approve or reject it.",
               {"programme": {"type": "string", "enum": MEMORY_VALUES["programme"]}}, ["programme"], True),
]


class ToolError(Exception):
    pass


class ToolService:
    def __init__(self, actor, run_id, question, handbook, profile="a2"):
        self.actor, self.run_id, self.question = actor, run_id, question
        self.handbook = handbook
        self.definitions = [d for d in DEFINITIONS if profile == "a2" or d["function"]["name"] != "request_programme_change"]

    def execute(self, name, arguments):
        db = get_db()
        schema = next((d["function"]["parameters"] for d in self.definitions if d["function"]["name"] == name), None)
        if not schema:
            return self._fail("unknown_tool", "Unknown or unavailable tool.", "unknown_tool")
        try:
            args = json.loads(arguments) if isinstance(arguments, str) else arguments
            if not isinstance(args, dict):
                raise ToolError("Tool arguments must be an object.")
            if set(args) - set(schema["properties"]) or set(schema["required"]) - set(args):
                raise ToolError("Missing or unexpected tool arguments.")
            for key, value in args.items():
                field = schema["properties"][key]
                if not isinstance(value, str) or not value.strip() or len(value) > 2000:
                    raise ToolError("Arguments must be nonempty text of at most 2000 characters.")
                if "enum" in field and value not in field["enum"]:
                    raise ToolError("Unsupported option. Ask the student to select an available option.")
            target = args.get("student_id", self.actor)
            if target != self.actor:
                audit(self.actor, name, "another_student", "denied", "ownership_mismatch", self.run_id)
                db.commit()
                return {"ok": False, "error": "Access denied. You may only access your own private student data.", "decision": "denied"}
            if any(sensitive(v) for k, v in args.items() if k not in ("student_id", "key")):
                raise ToolError("Sensitive content cannot be submitted to this tool.")
            result = self._dispatch(name, args)
            status = "pending" if result.get("approval") else None
            audit(self.actor, name, self.actor, "allowed", "pending_confirmation" if status else "success", self.run_id, status)
            db.commit()
            return {"ok": True, "decision": "allowed", **result}
        except (ValueError, TypeError, ToolError) as exc:
            db.rollback()
            message = str(exc) if isinstance(exc, ToolError) else "Malformed tool arguments. Please provide the missing information."
            return self._fail(name, message, "invalid_arguments")
        except Exception:
            db.rollback()
            # No raw exception text or arbitrary arguments in the audit trail.
            return self._fail(name, "The tool is temporarily unavailable. No successful change is confirmed.", "tool_error")

    def _fail(self, name, message, result):
        audit(self.actor, name, self.actor, "denied" if result != "tool_error" else "error", result, self.run_id)
        get_db().commit()
        return {"ok": False, "error": message, "decision": "error" if result == "tool_error" else "denied"}

    def _dispatch(self, name, args):
        db = get_db()
        if name == "search_policy":
            return {"chunks": self.handbook.search(args["query"]), "notice": "Use only matching evidence. If insufficient, say so and offer escalation."}
        if name in ("get_student_record", "get_fee_status", "get_scholarship_status"):
            columns = {"get_student_record": "id,name,programme,email", "get_fee_status": "fee_total,fee_paid,fee_due",
                       "get_scholarship_status": "scholarship,scholarship_status,scholarship_amount"}[name]
            record = db.execute(f"SELECT {columns} FROM students WHERE id=?", (self.actor,)).fetchone()
            if not record:
                raise ToolError("Your record was not found. Contact student services.")
            data = dict(record)
            if name == "get_fee_status":
                data.update(outstanding=data["fee_total"] - data["fee_paid"], currency="INR")
            if name == "get_scholarship_status":
                data["currency"] = "INR"
            return {"record": data}
        if name == "list_support_requests":
            return {"tickets": rows("SELECT id,category,description,status,created_at FROM tickets WHERE student_id=? ORDER BY created_at DESC LIMIT 20", (self.actor,))}
        if name == "create_support_request":
            # Deduplicate retries within this run without silently discarding future requests.
            existing = db.execute("SELECT id FROM tickets WHERE student_id=? AND run_id=? AND category=? AND description=?",
                                  (self.actor, self.run_id, args["category"], args["description"])).fetchone()
            ticket_id = existing["id"] if existing else "TKT-" + uuid.uuid4().hex[:12]
            if not existing:
                stamp = now()
                db.execute("""INSERT INTO tickets (id,student_id,category,description,status,created_at,run_id,updated_at)
                              VALUES (?,?,?,?,?,?,?,?)""", (ticket_id, self.actor, args["category"], args["description"], "open", stamp, self.run_id, stamp))
            return {"ticket_id": ticket_id, "status": "open", "delivery": "local_demo_only",
                    "notice": "Saved locally in the demo. No real support team is emailed; it appears in the demo staff console and no response time is promised."}
        if name == "remember_preference":
            if not memory_consent(self.question, args["key"], args["value"]):
                raise ToolError("Memory was not saved. Explicitly ask to remember an allowed preference; temporary or sensitive facts are never saved.")
            db.execute("INSERT INTO memory VALUES (?,?,?,?) ON CONFLICT(student_id,key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                       (self.actor, args["key"], args["value"], now()))
            return {"remembered": {"key": args["key"], "value": args["value"]}}
        if name == "request_programme_change":
            current = db.execute("SELECT programme FROM students WHERE id=?", (self.actor,)).fetchone()["programme"]
            if current == args["programme"]:
                raise ToolError("You are already in that programme; no change is needed.")
            existing = db.execute("SELECT * FROM approvals WHERE student_id=? AND status='pending' AND new_value=? AND expires_at>?",
                                  (self.actor, args["programme"], now())).fetchone()
            if existing:
                return {"approval": dict(existing), "message": "Awaiting student confirmation, then Student Services staff review. No record has changed."}
            approval_id = uuid.uuid4().hex
            expiry = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
            db.execute("""INSERT INTO approvals (id,student_id,field,old_value,new_value,status,created_at,expires_at,decided_at,run_id)
                          VALUES (?,?,?,?,?,?,?,?,?,?)""",
                       (approval_id, self.actor, "programme", current, args["programme"], "pending", now(), expiry, None, self.run_id))
            return {"approval": dict(db.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()),
                    "message": "Awaiting student confirmation, then Student Services staff review. No record has changed."}
        raise ToolError("Unavailable tool.")


def decide_approval(actor, approval_id, decision):
    """Student step: confirm sends the request to staff review; nothing changes yet. Not an LLM tool."""
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute("SELECT * FROM approvals WHERE id=? AND student_id=?", (approval_id, actor)).fetchone()
        if not row:
            audit(actor, "decide_approval", "unavailable_approval", "denied", "not_found")
            db.commit()
            return {"error": "Approval not found."}, 404
        status, code = row["status"], 200
        if status != "pending":
            audit(actor, "decide_approval", actor, "denied", "already_decided", row["run_id"], status)
            db.commit()
            return {"error": "This request has already been decided.", "status": status}, 409
        if row["expires_at"] <= now():
            status, code = "expired", 409
        elif decision == "reject":
            status = "rejected"
        else:
            current = db.execute("SELECT programme FROM students WHERE id=?", (actor,)).fetchone()["programme"]
            status, code = ("stale", 409) if current != row["old_value"] else ("awaiting_staff", 200)
        db.execute("UPDATE approvals SET status=?,decided_at=? WHERE id=? AND student_id=?", (status, now(), approval_id, actor))
        audit(actor, "decide_approval", actor, "confirmed" if status == "awaiting_staff" else "not_executed",
              "sent_to_staff_review" if status == "awaiting_staff" else status, row["run_id"], status)
        db.commit()
        return {"status": status, "executed": False, "new_value": row["new_value"]}, code
    except Exception:
        db.rollback()
        raise


def review_approval(staff_id, approval_id, decision):
    """Staff step: the only path that changes the record. Atomic check-and-update; not an LLM tool."""
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
        if not row:
            audit(staff_id, "review_approval", "unavailable_approval", "denied", "not_found")
            db.commit()
            return {"error": "Approval not found."}, 404
        if row["status"] != "awaiting_staff":
            audit(staff_id, "review_approval", row["student_id"], "denied", "not_awaiting_review", row["run_id"], row["status"])
            db.commit()
            return {"error": "This request is not awaiting staff review.", "status": row["status"]}, 409
        status, code = "rejected", 200
        if decision == "approve":
            current = db.execute("SELECT programme FROM students WHERE id=?", (row["student_id"],)).fetchone()["programme"]
            if current != row["old_value"]:
                status, code = "stale", 409
            else:
                db.execute("UPDATE students SET programme=? WHERE id=?", (row["new_value"], row["student_id"]))
                db.execute("DELETE FROM memory WHERE student_id=? AND key='programme'", (row["student_id"],))
                status = "approved"
        db.execute("UPDATE approvals SET status=?,reviewed_by=?,reviewed_at=? WHERE id=?", (status, staff_id, now(), approval_id))
        audit(staff_id, "review_approval", row["student_id"], "approved" if status == "approved" else "not_executed",
              "programme_updated" if status == "approved" else status, row["run_id"], status)
        db.commit()
        return {"status": status, "executed": status == "approved", "new_value": row["new_value"]}, code
    except Exception:
        db.rollback()
        raise
