import json
import subprocess
from unittest.mock import patch

import pytest
import yaml

from app.adapters.oasdiff import OasdiffEngine
from app.domain.models import GuardError
from app.services.specifications import parse_specification


def test_yaml_json_hash_and_original(specification):
    encoded = json.dumps(specification).encode()
    first = parse_specification(encoded, "api.json", 10000)
    second = parse_specification(yaml.safe_dump(specification).encode(), "api.yaml", 10000)
    assert first.content_hash == second.content_hash
    assert first.original == encoded.decode()


def test_size_and_depth_limits(specification):
    with pytest.raises(GuardError) as error:
        parse_specification(b"x" * 10001, "api.json", 10000)
    assert error.value.status == 413
    child = specification
    for _ in range(70):
        child["x-nested"] = {}
        child = child["x-nested"]
    with pytest.raises(GuardError, match="complexity"):
        parse_specification(json.dumps(specification).encode(), "api.json", 10000)


@pytest.mark.parametrize(
    "component",
    [
        {"schemas": {"A": {"$dynamicRef": "#/components/schemas/A"}}},
        {"pathItems": {"A": {}}},
    ],
)
def test_unsupported_coverage_is_rejected(specification, component):
    specification["components"] = component
    with pytest.raises(GuardError, match="not supported"):
        parse_specification(json.dumps(specification).encode(), "api.json", 10000)


def test_engine_timeout_and_missing_binary():
    engine = OasdiffEngine("missing")
    with patch(
        "app.adapters.oasdiff.subprocess.run", side_effect=subprocess.TimeoutExpired("oasdiff", 1)
    ):
        with pytest.raises(GuardError) as error:
            engine._run(["--version"], ".")
        assert error.value.status == 504
    with patch("app.adapters.oasdiff.subprocess.run", side_effect=FileNotFoundError):
        with pytest.raises(GuardError) as error:
            engine._run(["--version"], ".")
        assert error.value.status == 503


def test_engine_version_and_protocol_errors(specification):
    engine = OasdiffEngine()
    with patch.object(engine, "_run", return_value="oasdiff version 0.0.0"):
        with pytest.raises(GuardError) as error:
            engine.compare(specification, specification)
        assert error.value.code == "engine_version_mismatch"
    with patch.object(engine, "_run", side_effect=["oasdiff version 1.34.0", "{}", "{}"]):
        with pytest.raises(GuardError) as error:
            engine.compare(specification, specification)
        assert error.value.code == "engine_protocol_error"


def test_severity_mapping_preserves_warning_and_info(specification):
    engine = OasdiffEngine()
    items = [
        {"id": f"rule-{level}", "level": level, "path": "/items", "operation": "GET"}
        for level in [1, 2, 3, 99]
    ]
    with patch.object(
        engine, "_run", side_effect=["oasdiff version 1.34.0", json.dumps(items), "{}"]
    ):
        findings = engine.compare(specification, specification)
    assert {f.severity for f in findings} == {
        "non_breaking",
        "potentially_breaking",
        "breaking",
        "informational",
    }


def test_engine_failure_is_an_api_error(client, monkeypatch):
    def failed(*args):
        raise GuardError("Comparison engine timed out", 504, "engine_timeout")

    from test_api import create, upload

    base = {"openapi": "3.0.3", "info": {"title": "Test", "version": "1"}, "paths": {}}
    project = create(client)
    version = upload(client, project, base, "v1").json()
    monkeypatch.setattr(OasdiffEngine, "compare", failed)
    response = client.post(
        f"/api/v1/projects/{project}/comparisons",
        json={"baseline_id": version["id"], "candidate_id": version["id"]},
    )
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "engine_timeout"
    assert client.get(f"/api/v1/projects/{project}/comparisons").json() == []
