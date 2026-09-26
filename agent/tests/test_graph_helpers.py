from langchain_core.messages import AIMessage

from agent.graph import (
    _route_after_investigate,
    _route_after_remediation_plan,
    _status_code,
)


def _state_with(message):
    return {
        "messages": [message],
        "incident": "test",
        "diagnosis": None,
        "approval": "not_required",
        "verification": None,
        "verify_attempts": 0,
        "investigation_tool_results": 0,
        "remediation_action": None,
        "remediation_args": None,
        "remediation_result": None,
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


def test_route_to_approval_when_mutation_tool_call_is_proposed():
    message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "cleanup_training_logs",
                "args": {"service": "tomcat"},
                "id": "m1",
                "type": "tool_call",
            }
        ],
    )
    assert _route_after_remediation_plan(_state_with(message)) == "approval"


def test_route_to_report_when_no_mutation_tool_call_is_proposed():
    assert (
        _route_after_remediation_plan(_state_with(AIMessage(content="manual")))
        == "report"
    )


def test_status_code_extraction():
    assert _status_code({"status_code": 200}) == 200
    assert _status_code('{"status_code": 503}') == 503
    assert _status_code("something status_code=500 happened") == 500
