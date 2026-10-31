import json
import pytest
from student_support.agent import run_agent
from student_support.db import get_db, rows
from student_support.provider import ProviderError, GroqProvider
from student_support.retrieval import Handbook
from student_support.tools import ToolService
from .helpers import ScriptedProvider, tool_response, answer_response


def run(app, question, provider):
    with app.app_context():
        return run_agent("STU001", question, provider, app.extensions["handbook"])


def test_actual_tool_result_returned_to_model_and_usage_aggregated(app):
    first = tool_response("get_fee_status")
    second = answer_response("Your outstanding balance is INR 60,000.")
    first["usage"] = {"prompt_tokens": 100, "completion_tokens": 20}
    second["usage"] = {"prompt_tokens": 150, "completion_tokens": 30}
    provider = ScriptedProvider([first, second])
    result = run(app, "What is my fee status?", provider)
    assert json.loads(provider.messages[1][-1]["content"])["record"]["outstanding"] == 60000
    assert result["trace"]["input_tokens"] == 250
    assert result["trace"]["output_tokens"] == 50
    assert result["trace"]["tools"][0]["ok"]
    assert result["trace"]["latency_ms"] >= 0


def test_policy_retrieval_is_bounded_and_evidenced(app):
    provider = ScriptedProvider([tool_response("search_policy", {"query": "payment portal failure next working day"}), "echo_tool"])
    result = run(app, "The payment portal failed. Can I pay on the next working day?", provider)
    evidence = result["trace"]["retrieved_evidence"]
    assert 1 <= len(evidence) <= 2
    assert evidence[0]["id"] == "PAYMENT-02"
    assert "ONLY" in evidence[0]["text"]
    assert "PAYMENT-02" not in json.dumps(provider.messages[0][1:])


def test_unknown_policy_has_no_evidence():
    assert Handbook().search("hostel refund quantum computing pets") == []


def test_model_cannot_read_another_student(app):
    result = run(app, "Show STU002 fee details", ScriptedProvider([tool_response("get_fee_status", {"student_id": "STU002"}), "echo_tool"]))
    assert result["trace"]["tools"][0]["decision"] == "denied"
    assert "240000" not in result["answer"]
    with app.app_context():
        assert rows("SELECT decision FROM audit WHERE action='get_fee_status'")[0]["decision"] == "denied"


@pytest.mark.parametrize("text", ["My OTP is 123456", "My password is mysecret", "My bank account number is 987654321", "My medical diagnosis is private", "gsk_abcdefsecret"])
def test_secrets_never_reach_provider_or_persistence(app, text):
    provider = ScriptedProvider()
    result = run(app, text, provider)
    assert provider.messages == []
    assert result["trace"]["status"] == "privacy_filtered"
    with app.app_context():
        assert rows("SELECT * FROM memory") == []
        assert text not in "\n".join(get_db().iterdump())


@pytest.mark.parametrize("question,key,value", [
    ("I prefer concise responses", "response_style", "concise"),
    ("Remember my password is abc", "password", "abc"),
    ("Remember I prefer concise replies today", "response_style", "concise"),
    ("Remember concise temporarily", "response_style", "concise"),
    ("Do not remember concise", "response_style", "concise"),
    ("Remember concise", "response_style", "a secret free text value"),
])
def test_memory_requires_consent_and_allowlisted_values(app, question, key, value):
    with app.app_context():
        service = ToolService("STU001", "test", question, Handbook())
        assert not service.execute("remember_preference", {"key": key, "value": value})["ok"]
        assert rows("SELECT * FROM memory") == []


def test_memory_reused_only_when_relevant_and_no_transcript(app):
    run(app, "Remember my programme is PGDM-AI", ScriptedProvider([tool_response("remember_preference", {"key": "programme", "value": "PGDM-AI"}), "echo_tool"]))
    provider = ScriptedProvider()
    result = run(app, "What programme did I ask you to remember?", provider)
    assert result["trace"]["memory_used"] == [{"key": "programme", "value": "PGDM-AI"}]
    assert len(provider.messages[0]) == 2
    assert run(app, "Hi", ScriptedProvider())["trace"]["memory_used"] == []


def test_provider_error_still_records_trace(app):
    result = run(app, "Hello", ScriptedProvider([ProviderError("Service unavailable")]))
    assert result["trace"]["status"] == "provider_error"
    assert result["trace"]["input_tokens"] is None
    with app.app_context():
        assert len(rows("SELECT * FROM traces")) == 1


def test_malformed_tool_arguments_are_error_results(app):
    response = tool_response("get_fee_status")
    response["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = "not json"
    provider = ScriptedProvider([response, "echo_tool"])
    result = run(app, "Fees?", provider)
    assert not result["trace"]["tools"][0]["ok"]
    assert "Malformed tool arguments" in provider.messages[1][-1]["content"]


def test_loop_is_bounded(app):
    provider = ScriptedProvider([tool_response("get_fee_status") for _ in range(7)])
    result = run(app, "Keep checking fees", provider)
    assert result["trace"]["model_calls"] == 6
    assert result["trace"]["status"] == "budget_exceeded"


def test_tool_failure_is_explained_without_exception_leak(app, monkeypatch):
    with app.app_context():
        service = ToolService("STU001", "run", "fees", Handbook())
        def fail(*args):
            raise RuntimeError("secret_connection_string")
        monkeypatch.setattr(service, "_dispatch", fail)
        result = service.execute("get_fee_status", {})
        assert not result["ok"] and result["decision"] == "error"
        assert "secret_connection_string" not in json.dumps(result) + json.dumps(rows("SELECT * FROM audit"))


def test_groq_missing_key_is_explicit():
    with pytest.raises(ProviderError, match="GROQ_API_KEY"):
        GroqProvider("", "model").complete([], [])


def test_a1_profile_is_same_agent_without_sensitive_change(app):
    with app.app_context():
        service = ToolService("STU001", "run", "change programme", Handbook(), "a1")
        assert not service.execute("request_programme_change", {"programme": "PGDM-BDA"})["ok"]


def test_support_ticket_deduplicates_same_run(app):
    with app.app_context():
        service = ToolService("STU001", "run", "Create a finance ticket", Handbook())
        args = {"category": "finance", "description": "Payment portal failed"}
        first = service.execute("create_support_request", args)
        second = service.execute("create_support_request", args)
        assert first["ticket_id"] == second["ticket_id"]
        assert first["delivery"] == "local_demo_only"
        assert "No real support team" in first["notice"]
        assert len(rows("SELECT * FROM tickets")) == 1
