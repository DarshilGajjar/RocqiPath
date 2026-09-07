"""Local Studio API integration and containment regressions."""

import time
from pathlib import Path

import pytest
from PIL import Image

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from rocqipath.studio.server import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "workspace")) as session:
        yield session


def test_folder_scan_metadata_and_tile(client, tmp_path):
    folder = tmp_path / "slides"
    folder.mkdir()
    Image.new("RGB", (640, 480), (170, 100, 130)).save(folder / "example.tif")
    response = client.post("/api/folders", json={"path": str(folder)})
    assert response.status_code == 200, response.text
    slides = client.get("/api/slides").json()
    assert len(slides) == 1
    info = client.get(f"/api/slides/{slides[0]['id']}/info").json()
    assert (info["width"], info["height"]) == (640, 480)
    tile = client.get(f"/api/slides/{slides[0]['id']}/tiles/10/0/0.jpg")
    assert tile.status_code == 200
    assert tile.headers["content-type"] == "image/jpeg"
    assert client.get("/api/slides/not-registered/thumbnail").status_code == 404


def test_cross_origin_mutations_and_unknown_workflows_rejected(client):
    assert client.post("/api/demo", headers={"origin": "https://evil.example"}, json={}).status_code == 403
    assert client.post("/api/jobs", json={"workflow": "shell", "slide_ids": []}).status_code == 422


def test_real_count_job_and_artifact_containment(client, tmp_path):
    folder = tmp_path / "slides"
    folder.mkdir()
    Image.new("RGB", (128, 128), (110, 70, 35)).save(folder / "sample.tif")
    client.post("/api/folders", json={"path": str(folder)})
    slide = client.get("/api/slides").json()[0]
    result = client.post("/api/jobs", json={
        "workflow": "count", "slide_ids": [slide["id"]],
        "parameters": {"source_magnification": 20, "target_magnification": 20},
    })
    assert result.status_code == 200, result.text
    job_id = result.json()["id"]
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] not in {"queued", "running"}:
            break
        time.sleep(0.1)
    assert job["status"] == "succeeded", job
    assert any(a["name"].endswith(".json") for a in job["artifacts"])
    assert client.get(f"/api/jobs/{job_id}/artifact?path=../../studio.sqlite").status_code == 403
    artifact = job["artifacts"][0]
    assert client.get(f"/api/jobs/{job_id}/artifact", params={"path": artifact["path"]}).status_code == 200


def test_history_survives_restart(tmp_path):
    workspace = tmp_path / "work"
    with TestClient(create_app(workspace)) as client:
        client.post("/api/folders", json={"path": str(tmp_path)})
    with TestClient(create_app(workspace)) as client:
        assert len(client.get("/api/folders").json()) == 1
