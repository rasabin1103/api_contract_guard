import os
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient

from alembic import command
from app.adapters.oasdiff import OasdiffEngine
from app.core.config import Settings
from app.main import create_app

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def engine():
    executable = os.environ.get("ACG_OASDIFF_PATH", str(ROOT / "tools/bin/oasdiff.exe"))
    return OasdiffEngine(executable)


@pytest.fixture
def client(tmp_path, monkeypatch, engine):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("ACG_DATABASE_URL", url)
    config = Config(str(ROOT / "backend/alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend/alembic"))
    command.upgrade(config, "head")
    app = create_app(Settings(database_url=url), engine)
    with TestClient(app) as value:
        yield value
    app.state.database.dispose()


@pytest.fixture
def specification():
    return {
        "openapi": "3.0.3",
        "info": {"title": "Inventory", "version": "1.0"},
        "paths": {
            "/items": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["id", "name"],
                                        "properties": {
                                            "id": {"type": "integer"},
                                            "name": {"type": "string"},
                                        },
                                    }
                                }
                            },
                        }
                    }
                }
            }
        },
    }
