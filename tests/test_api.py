"""Tests for the Flask API: inputs are validated, results are computed (not
hard-coded), and every response is labelled as a simulation."""

import pytest

from outrun.web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def run(client, **changes):
    body = {"seed": 7, "k": 10, "quake_x_km": 100.0, "quake_y_km": 90.0,
            "you_x_km": 150.0, "you_y_km": 110.0}
    body.update(changes)
    return client.post("/api/run", json=body)


def test_world_has_phones_and_towns_but_no_quake(client):
    data = client.get("/api/world?seed=7").get_json()
    assert data["simulation"] is True
    assert len(data["phones"]) == 2700 and len(data["towns"]) == 3
    assert "quake" not in data and "truth" not in data
    assert data["k"] == {"min": 4, "max": 40, "default": 10}


@pytest.mark.parametrize("seed", ["abc", "-1", "2000000"])
def test_world_rejects_bad_seed(client, seed):
    assert client.get(f"/api/world?seed={seed}").status_code == 400


def test_run_returns_computed_alert_and_warnings(client):
    res = run(client)
    assert res.status_code == 200
    data = res.get_json()
    assert data["simulation"] is True
    assert data["alert"] is not None
    assert data["alert"]["location_error_km"] < 5.0
    assert {p["name"] for p in data["places"]} == {"You", "Northville", "Eastport", "Southbridge"}
    assert data["reports"] and all("trusted" in r and "processed" in r for r in data["reports"])


def test_run_results_depend_on_where_the_quake_is(client):
    """Not hard-coded: different quakes give different alerts and estimates."""
    a = run(client, quake_x_km=100.0, quake_y_km=90.0).get_json()["alert"]
    b = run(client, quake_x_km=60.0, quake_y_km=140.0).get_json()["alert"]
    assert a["estimate"]["x_km"] != b["estimate"]["x_km"]
    assert a["seconds_after_quake_start"] != b["seconds_after_quake_start"]


def test_run_is_reproducible(client):
    assert run(client).get_json() == run(client).get_json()


def test_larger_k_alerts_later(client):
    early = run(client, k=4).get_json()["alert"]["seconds_after_quake_start"]
    late = run(client, k=40).get_json()["alert"]["seconds_after_quake_start"]
    assert late > early


def test_moving_you_changes_only_your_warning(client):
    near = run(client, you_x_km=110.0, you_y_km=90.0).get_json()
    far = run(client, you_x_km=190.0, you_y_km=190.0).get_json()
    assert near["alert"] == far["alert"]
    you_near = next(p for p in near["places"] if p["name"] == "You")
    you_far = next(p for p in far["places"] if p["name"] == "You")
    assert you_far["predicted_warning_s"] > you_near["predicted_warning_s"]


@pytest.mark.parametrize("changes", [
    {"k": 3}, {"k": 41}, {"k": 10.5}, {"k": True},
    {"quake_x_km": -1.0}, {"quake_y_km": 200.5}, {"quake_x_km": "50"},
    {"seed": -1}, {"you_x_km": 500.0},
])
def test_run_rejects_invalid_input(client, changes):
    res = run(client, **changes)
    assert res.status_code == 400 and "error" in res.get_json()


def test_run_requires_json_object(client):
    assert client.post("/api/run", data="not json").status_code == 400
    assert client.post("/api/run", json=[1, 2, 3]).status_code == 400


def test_hidden_test_runs_unseen_quakes(client):
    data = client.post("/api/hidden-test", json={"k": 10, "n": 5, "batch": 0}).get_json()
    assert data["simulation"] is True and data["stream"] == "validation"
    assert data["quakes"] == 5 and len(data["errors_km"]) <= 5
    other = client.post("/api/hidden-test", json={"k": 10, "n": 5, "batch": 1}).get_json()
    assert other["first_seed"] != data["first_seed"]


@pytest.mark.parametrize("body", [{"n": 0}, {"n": 61}, {"k": 2}, {"batch": -1}])
def test_hidden_test_rejects_invalid_input(client, body):
    assert client.post("/api/hidden-test", json=body).status_code == 400


def test_false_alarms_reports_measuring_or_ready(client):
    data = client.get("/api/false-alarms").get_json()
    assert data["status"] in ("measuring", "ready")
