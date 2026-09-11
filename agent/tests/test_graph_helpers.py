from langchain_core.messages import AIMessage

from agent.graph import _route_after_investigate, _status_code


def _state_with(message):
    return {
        "messages": [message],
        "incident": "test",
        "diagnosis": None,
        "approval": "not_required",
        "verification": None,
        "verify_attempts": 0,
        "report": None,
    }


def test_route_to_tools_when_model_requested_tool():
    message = AIMessage(
        content="",
        tool_calls=[{"name": "list_containers", "args": {}, "id": "x", "type": "tool_call"}],
    )
    assert _route_after_investigate(_state_with(message)) == "tools"


def test_route_to_judge_when_model_finishes():
    assert _route_after_investigate(_state_with(AIMessage(content="done"))) == "judge"


def test_status_code_extraction():
    assert _status_code({"status_code": 200}) == 200
    assert _status_code('{"status_code": 503}') == 503
    assert _status_code("something status_code=500 happened") == 500
