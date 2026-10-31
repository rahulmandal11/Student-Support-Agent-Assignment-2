# Privacy and approval rules

## Identity and authorization

The browser signs in with a student ID and password. Werkzeug stores password hashes; Flask's
signed, HttpOnly, SameSite session carries only the verified student ID, CSRF token, conversation
ID and expiry metadata. Neither a model instruction nor an HTTP body can change the acting student.
Every private SQL read/write uses the session subject. Optional tool targets that name another
student are denied in `ToolService.execute` before the query. A denied audit event is recorded.
Unknown targets and unavailable approval/trace IDs reveal no existence information.

Authenticated APIs expose only that student's memory, support requests, approval proposals,
traces and audit events. CSRF is checked on all mutating routes, including login. Login attempts
are rate-limited in process. The application has no unauthenticated private-record endpoint.

## Storage boundaries

| Information | Treatment |
|---|---|
| Chat history | Each question and answer is saved in SQLite (`conversations`, `messages`), scoped to the signed-in student and listed under Chat history. The owner can reopen, export or delete a conversation; staff and admins cannot read it. A privacy-filtered message is stored only as a "Message hidden" placeholder |
| Model context | Still not the full transcript: at most one recent exchange in server RAM for 15-minute clarification context (restored from history when a conversation is reopened) |
| Secrets marked as OTP/password/bank/card/health data, long numeric sequences or Groq key patterns | Conservative whole-message filter before the provider; no raw trace question or memory |
| Useful durable preferences | Only programme, response language or response style, with enumerated values and explicit consent |
| Temporary information | Never accepted as durable memory; may be temporary context until new conversation/sign-out/expiry |
| Tool arguments | Validated; never copied wholesale to traces/audit |
| Support descriptions and replies | Persist only on ticket creation or reply, after sensitive-content filtering; visible to the owner and staff |
| Trace/audit | Metadata, fixed policy evidence, allowlisted memory, tool/approval identifiers; no raw chat, provider exceptions or API keys |
| API key | Local `.env` or process environment only; not returned to browser |

Memory consent must come from the current student request containing `remember` or `save` plus
the selected value, without negation or temporary markers, or from the explicit UI checkbox.
No free-text memory field exists. Preference deletion is available to its owner.

## Sensitive-action state machine

```text
request_programme_change
  └─ pending (original record unchanged; expires in 30 minutes)
       ├─ student Confirm → awaiting_staff (record still unchanged)
       │     ├─ staff Approve → approved + atomic record update
       │     ├─ staff Reject  → rejected, no update
       │     └─ original value changed → stale, no update
       ├─ student Reject      → rejected, no update
       ├─ decision after expiry → expired, no update
       └─ original value changed → stale, no update
```

The programme and old/new values are stored in the pending proposal. The student endpoint
accepts only `confirm` or `reject`, and the staff endpoint only `approve` or `reject`, never a
replacement value. Both use `BEGIN IMMEDIATE` and check status and the current record in one
transaction; only the staff approval updates the programme. Approved changes clear a possibly
stale remembered programme preference. All terminal states reject replay. The LLM has no tool to
decide or review an approval. Staff see only requests the student has already confirmed, and the
audit trail records the student's confirmation and the reviewing staff member separately.

## Staff and admin access

Staff and admin accounts sign in through a separate endpoint and cannot use any student route
(chat, history, memory, traces, approvals, export or profile). Staff see support requests with
their reply threads and confirmed programme-change requests. Admins additionally see account
lists (never password hashes) and the full audit log. The role is re-read from the database on
every request. Ticket replies from either side go through the same sensitive-content filter.

## Audit interpretation

Each event identifies timestamp, actor, action, target, decision, approval status, result and
agent run ID when applicable. A proposal's `allowed/pending_confirmation` event is not an
executed change. Only `decide_approval → approved → programme_updated` records execution.
Rejected, expired, stale and foreign requests record a non-execution/denial outcome.
The audit API is read-only; SQLite remains locally editable by the machine owner, so these
records are application audit evidence, not cryptographically tamper-proof records.

## Required scenario coverage

- Own fee/scholarship: allowed; actual owner-scoped tool result returned.
- Other student's data: denied before private query, even under malicious model tool arguments.
- Own sensitive change: pending only; no update until the student confirms and staff approve.
- Rejected change (by student or staff): record unchanged; a later confirm or approve returns a conflict.
- OTP/password: filtered before model use and absent from database memory and chat history.
- Traces, latency and tokens: same instrumentation remains active after final safety controls.
