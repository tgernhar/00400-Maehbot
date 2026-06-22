"""FastAPI endpoint tests."""

import pytest
from fastapi.testclient import TestClient

import web.backend.app as app_module
from web.backend.app import app, get_app_state


@pytest.fixture()
def client(tmp_path):
    app_module._state.clear()
    root = tmp_path / "data"
    root.mkdir()

    def _state():
        from maehbot.config_loader import load_config
        from storage.database import Database
        from storage.paths import StoragePaths
        from web.backend.auth import hash_password

        if not app_module._state:
            config = load_config()
            config.setdefault("storage", {})["root_path"] = str(root)
            paths = StoragePaths(str(root))
            paths.ensure()
            app_module._state["config"] = config
            app_module._state["paths"] = paths
            app_module._state["db"] = Database(paths.db_path)
            app_module._state["password_hash"] = hash_password("maehbot")
        return app_module._state

    app.dependency_overrides[get_app_state] = _state
    yield TestClient(app)
    app.dependency_overrides.clear()
    app_module._state.clear()


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_spray_config_get(client):
    r = client.get("/api/config/spray")
    assert r.status_code == 200
    assert "delay_ms" in r.json()


def test_mode_config_get(client):
    r = client.get("/api/config/mode")
    assert r.status_code == 200
    assert r.json()["test_mode"] is True


def test_spa_training_route(client):
    dist = app_module._frontend_dist
    if not dist.is_dir():
        pytest.skip("frontend dist not built")
    r = client.get("/training")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "Maehbot" in r.text or "root" in r.text


def test_snapshot_recording_queues_command(client, tmp_path):
    from training.recording import consume_recording_command

    state = app.dependency_overrides[get_app_state]()
    paths = state["paths"]
    r = client.post("/api/training/record/snapshot", json={"name": "Einzelbild"})
    assert r.status_code == 200
    cmd = consume_recording_command(paths)
    assert cmd is not None
    assert cmd["action"] == "snapshot"
    assert cmd["name"] == "Einzelbild"
