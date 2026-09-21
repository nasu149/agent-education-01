"""Dashboard delivery must work independently of the process working directory."""

from html.parser import HTMLParser

from fastapi.testclient import TestClient

from agent.api import app


class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "link" and attrs.get("rel") == "stylesheet":
            self.assets.append((attrs["href"], "text/css"))
        elif tag == "script" and "src" in attrs:
            self.assets.append((attrs["src"], "javascript"))


def test_dashboard_and_linked_assets_are_served(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    # No lifespan context: serving the UI must not start monitoring or call Gemini.
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "一次障害対応Agent" in response.text

    parser = AssetParser()
    parser.feed(response.text)
    assert len(parser.assets) == 2
    for url, content_type in parser.assets:
        asset = client.get(url)
        assert asset.status_code == 200
        assert content_type in asset.headers["content-type"]
        assert asset.content

    assert client.get("/static/missing.js").status_code == 404
    assert client.get("/static/%2e%2e/api.py").status_code == 404
