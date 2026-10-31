"""Bounded, volatile clarification context. Never written to SQLite or session cookies."""
import re
import time
from threading import Lock

from .privacy import sensitive


class ConversationContext:
    def __init__(self, ttl_seconds=900):
        self.entries = {}
        self.ttl = ttl_seconds
        self.lock = Lock()

    def _prune(self):
        cutoff = time.monotonic() - self.ttl
        self.entries = {k: v for k, v in self.entries.items() if v[0] > cutoff}

    def select(self, session_id, question):
        with self.lock:
            self._prune()
            entry = self.entries.get(session_id)
            if not entry:
                return []
            previous = entry[1]
            last_answer = previous[-1]["content"]
            # Include one exchange only for a clarification or an explicit follow-up.
            followup = re.search(r"\b(that|it|those|this issue|yes|no|also|instead|same)\b", question, re.I)
            short_clarification = "?" in last_answer and len(question.split()) <= 30
            return [dict(m) for m in previous] if followup or short_clarification else []

    def remember_exchange(self, session_id, question, answer):
        if sensitive(question) or sensitive(answer):
            return
        with self.lock:
            self._prune()
            self.entries[session_id] = (time.monotonic(), [{"role": "user", "content": question[:2000]},
                                                         {"role": "assistant", "content": answer[:4000]}])

    def clear(self, session_id):
        with self.lock:
            self.entries.pop(session_id, None)
