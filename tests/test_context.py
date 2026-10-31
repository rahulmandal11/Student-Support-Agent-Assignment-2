import time
from student_support.context import ConversationContext
from .helpers import ScriptedProvider, answer_response


def test_only_relevant_recent_context_is_selected():
    context = ConversationContext()
    context.remember_exchange("session", "Create a ticket", "What issue should I report?")
    assert len(context.select("session", "Payment portal failed")) == 2
    assert context.select("other-session", "Payment portal failed") == []
    context.remember_exchange("session", "What are my fees?", "Your balance is INR 60,000.")
    assert context.select("session", "Explain scholarship eligibility") == []
    assert len(context.select("session", "Create a ticket for that")) == 2


def test_temporary_context_expires_and_excludes_sensitive_text():
    context = ConversationContext(ttl_seconds=-1)
    context.remember_exchange("session", "Hi", "Hello")
    assert context.select("session", "yes") == []
    context = ConversationContext()
    context.remember_exchange("session", "My OTP is 123456", "Not saved")
    assert context.entries == {}


def test_new_conversation_clears_temporary_context(client, headers, app):
    provider = ScriptedProvider([answer_response("Which issue should I report?"), answer_response("Understood."), answer_response("Hello.")])
    app.extensions["provider"] = provider
    client.post("/api/chat", json={"message":"Create a support request"}, headers=headers)
    response = client.post("/api/chat", json={"message":"Payment portal failed"}, headers=headers)
    assert response.json["trace"]["context"]["history_messages"] == 2
    assert client.post("/api/conversation/new", headers=headers).status_code == 200
    response = client.post("/api/chat", json={"message":"What was that?"}, headers=headers)
    assert response.json["trace"]["context"]["history_messages"] == 0
