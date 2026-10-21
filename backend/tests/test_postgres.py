"""Opt-in smoke test against a dedicated PostgreSQL test database (CI service)."""

import os

import pytest
import yaml
from alembic.config import Config
from conftest import ROOT
from fastapi.testclient import TestClient
from test_api import upload

from alembic import command
from app.core.config import Settings
from app.main import create_app


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_URL"), reason="No dedicated PostgreSQL test server"
)
def test_postgres_migrations_and_crud(monkeypatch, engine):
    url = os.environ["TEST_POSTGRES_URL"]
    monkeypatch.setenv("ACG_DATABASE_URL", url)
    config = Config(str(ROOT / "backend/alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend/alembic"))
    command.upgrade(config, "head")
    app = create_app(Settings(database_url=url), engine)
    with TestClient(app) as client:
        created = client.post("/api/v1/projects", json={"name": "PostgreSQL smoke"})
        assert created.status_code == 201
        identifier = created.json()["id"]
        assert client.get(f"/api/v1/projects/{identifier}").json()["name"] == "PostgreSQL smoke"
        baseline = yaml.safe_load((ROOT / "examples/openapi-v1.yaml").read_text())
        candidate = yaml.safe_load((ROOT / "examples/openapi-v2-breaking.yaml").read_text())
        base_response = upload(client, identifier, baseline, "v1")
        target_response = upload(client, identifier, candidate, "v2")
        assert base_response.status_code == target_response.status_code == 201
        comparison = client.post(
            f"/api/v1/projects/{identifier}/comparisons",
            json={
                "baseline_id": base_response.json()["id"],
                "candidate_id": target_response.json()["id"],
            },
        )
        assert comparison.status_code == 201, comparison.text
        assert comparison.json()["summary"]["breaking"] == 4
        assert (
            client.get(f"/api/v1/comparisons/{comparison.json()['id']}/export").json()
            == comparison.json()
        )
        assert (
            client.delete(
                f"/api/v1/projects/{identifier}", params={"confirm_name": "PostgreSQL smoke"}
            ).status_code
            == 204
        )
    app.state.database.dispose()
