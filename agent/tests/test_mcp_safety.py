"""Static safety-contract tests that do not need Docker or Gemini."""

from mcp_server import server


def test_allowed_services_are_narrow():
    assert {"httpd", "tomcat", "postgres"}.issubset(server.ALLOWED_SERVICES)


def test_config_reader_is_whitelisted():
    assert set(server.CONFIG_TARGETS) == {"httpd_proxy", "tomcat_database"}
