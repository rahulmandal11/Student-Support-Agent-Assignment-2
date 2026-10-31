import json


def tool_response(name, args=None):
    return {"choices": [{"message": {"role": "assistant", "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": name, "arguments": json.dumps(args or {})}}]}}]}


def answer_response(content="Done."):
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


class ScriptedProvider:
    label = "scripted-test"
    model = "deterministic-fixture"

    def __init__(self, responses=None):
        self.responses = list(responses or [answer_response()])
        self.messages = []
        self.tool_definitions = []

    def complete(self, messages, tools):
        self.messages.append(json.loads(json.dumps(messages)))
        self.tool_definitions.append(tools)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if response == "echo_tool":
            return answer_response(messages[-1]["content"])
        return response
