"""Milestone 1 tests: the app starts, the health check works, the page loads
and carries the simulation notice."""

import pytest

from outrun.web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_health_returns_ok_json(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "ok"
    assert data["app"] == "outrun-the-earthquake"
    assert data["simulation"] is True
    assert "Not a real warning system" in data["notice"]


def test_index_page_loads_with_simulation_banner(client):
    res = client.get("/")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "SIMULATION" in html
    assert "Not a real warning system" in html


def test_static_assets_load(client):
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_unknown_route_is_404(client):
    assert client.get("/api/does-not-exist").status_code == 404
