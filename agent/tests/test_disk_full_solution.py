from agent.mcp_tools import MUTATING_TOOL_NAMES, READ_ONLY_TOOL_NAMES
from agent.models import Diagnosis


def test_disk_full_tools_are_classified_by_permission():
    assert {"get_disk_usage", "list_large_files"}.issubset(READ_ONLY_TOOL_NAMES)
    assert "cleanup_training_logs" in MUTATING_TOOL_NAMES
    assert "cleanup_training_logs" not in READ_ONLY_TOOL_NAMES


def test_diagnosis_accepts_disk_cleanup_action():
    diagnosis = Diagnosis(
        root_cause="研修用ディスクの容量枯渇",
        evidence=["/training-disk use_percent=100"],
        recommended_action="cleanup_training_logs",
        target_service="tomcat",
        target_application="none",
        action_reason="古い研修用ログだけを削除して空き容量を回復する",
        confidence="high",
    )
    assert diagnosis.recommended_action == "cleanup_training_logs"
