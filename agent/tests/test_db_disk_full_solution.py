from agent.mcp_tools import MUTATING_TOOL_NAMES, READ_ONLY_TOOL_NAMES
from agent.models import Diagnosis
from mcp_server import server


def test_db_disk_full_tools_are_classified_by_permission():
    assert {
        "get_postgres_training_disk_usage",
        "list_postgres_training_disk_files",
    }.issubset(READ_ONLY_TOOL_NAMES)
    assert "cleanup_postgres_training_exports" in MUTATING_TOOL_NAMES
    assert "cleanup_postgres_training_exports" not in READ_ONLY_TOOL_NAMES


def test_db_disk_full_cleanup_target_is_fixed():
    assert server.TRAINING_DB_DISK_SERVICE == "postgres"
    assert server.TRAINING_DB_DISK_PATH == "/training-disk"
    assert (
        server.TRAINING_DB_EXPORT_PATH
        == "/training-disk/archive/training-overnight-export.bin"
    )


def test_diagnosis_accepts_db_disk_cleanup_action():
    diagnosis = Diagnosis(
        root_cause="PostgreSQLの研修用ストレージが容量枯渇",
        evidence=["/training-disk use_percent=100"],
        recommended_action="cleanup_postgres_training_exports",
        target_service="postgres",
        target_application="none",
        action_reason="異常に肥大化したtraining-only exportを削除する",
        confidence="high",
    )
    assert diagnosis.recommended_action == "cleanup_postgres_training_exports"
