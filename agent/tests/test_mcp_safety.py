"""Static safety-contract tests that do not need Docker or Gemini."""

from mcp_server import server


def test_allowed_services_are_narrow():
    assert {"httpd", "tomcat", "postgres"}.issubset(server.ALLOWED_SERVICES)


def test_config_reader_is_whitelisted():
    assert set(server.CONFIG_TARGETS) == {"httpd_proxy", "tomcat_database"}


def test_database_remediation_is_narrowly_allowlisted():
    assert server.TERMINABLE_DB_APPLICATIONS == {"fault-injector"}
    assert server.FAULT_DB_USER == "fault_injector"


def test_plain_docker_container_fallbacks_are_explicit():
    assert server.CONTAINER_NAMES == {
        "httpd": "agent-education-httpd",
        "tomcat": "agent-education-tomcat",
        "postgres": "agent-education-postgres",
    }
