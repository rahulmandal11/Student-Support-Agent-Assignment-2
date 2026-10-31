"""Conservative, explainable demo privacy controls; not a universal DLP classifier."""
import re

MEMORY_VALUES = {
    "programme": ["PGDM-AI", "PGDM-BDA"],
    "response_language": ["English", "Hindi"],
    "response_style": ["concise", "detailed"],
}

SECRET_MARKERS = re.compile(
    r"\b(otp|one[ -]?time|password|passcode|pin|secret|api[ _-]?key|"
    r"bank|account number|card number|cvv|aadhaar|aadhar|ssn|"
    r"diagnos\w*|medical|health|medication)\b|gsk_[A-Za-z0-9]+|\b\d{6,}\b",
    re.I,
)


def sensitive(text):
    return bool(SECRET_MARKERS.search(text))


def memory_consent(question, key, value):
    """The model cannot manufacture consent or arbitrary free-text memory."""
    if sensitive(question) or not re.search(r"\b(remember|save)\b", question, re.I):
        return False
    if re.search(r"\b(don't|do not|never|forget|temporary|temporarily|today|tomorrow|tonight|this week|this session|for now)\b", question, re.I):
        return False
    return key in MEMORY_VALUES and value in MEMORY_VALUES[key] and value.casefold() in question.casefold()


def selected_memory(student_id, question):
    from .db import rows
    keys = ["response_language", "response_style"]
    if re.search(r"programme|program|course|study|studying|remember|recall", question, re.I):
        keys.append("programme")
    return [m for m in rows("SELECT key,value FROM memory WHERE student_id=?", (student_id,)) if m["key"] in keys]
