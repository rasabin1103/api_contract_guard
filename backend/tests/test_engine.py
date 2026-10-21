import copy
import json
import subprocess
import sys

import pytest

from app.domain.models import GuardError
from app.services.specifications import parse_specification


@pytest.mark.parametrize(
    "change", ["endpoint", "parameter", "field", "type", "status", "enum", "required"]
)
def test_breaking_rules(engine, specification, change):
    base = copy.deepcopy(specification)
    target = copy.deepcopy(base)
    operation = target["paths"]["/items"]["get"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    if change == "endpoint":
        target["paths"] = {}
    elif change == "parameter":
        operation["parameters"] = [
            {"name": "token", "in": "query", "required": True, "schema": {"type": "string"}}
        ]
    elif change == "field":
        schema["properties"].pop("name")
        schema["required"].remove("name")
    elif change == "type":
        schema["properties"]["id"]["type"] = "string"
    elif change == "status":
        operation["responses"] = {"201": {"description": "Created"}}
    elif change == "enum":
        base["paths"]["/items"]["get"]["parameters"] = [
            {"name": "sort", "in": "query", "schema": {"type": "string", "enum": ["a", "b"]}}
        ]
        operation["parameters"] = [
            {"name": "sort", "in": "query", "schema": {"type": "string", "enum": ["a"]}}
        ]
    elif change == "required":
        schema["required"].remove("name")
    findings = engine.compare(base, target)
    assert any(f.severity == "breaking" for f in findings), [f.to_dict() for f in findings]
    assert all(f.rule_id and f.id and f.engine_metadata for f in findings)
    assert [f.to_dict() for f in findings] == [f.to_dict() for f in engine.compare(base, target)]


def test_identical_and_optional_addition(engine, specification):
    assert engine.compare(specification, specification) == []
    target = copy.deepcopy(specification)
    target["paths"]["/items"]["get"]["responses"]["200"]["content"]["application/json"]["schema"][
        "properties"
    ]["note"] = {"type": "string"}
    findings = engine.compare(specification, target)
    assert not any(f.severity == "breaking" for f in findings)


def test_supplemental_diff_is_only_run_for_server_changes(engine, specification, monkeypatch):
    commands = []
    original = engine._run

    def tracked(arguments, directory):
        commands.append(arguments[0])
        return original(arguments, directory)

    monkeypatch.setattr(engine, "_run", tracked)
    assert engine.compare(specification, specification) == []
    assert commands == ["--version", "changelog"]
    commands.clear()
    target = {**specification, "servers": [{"url": "/api/v3"}]}
    assert any(f.category == "servers" for f in engine.compare(specification, target))
    assert commands == ["--version", "changelog", "diff"]


@pytest.mark.parametrize(
    "content, filename",
    [
        (b"{", "bad.json"),
        (b"a: 1\na: 2", "bad.yaml"),
        (b"openapi: 2.0", "bad.yaml"),
        (b"[]", "bad.json"),
        (b"a: &a [*a]", "bad.yaml"),
        (b"{}", "bad.txt"),
        (b'{"a": 1, "a": 2}', "bad.json"),
    ],
)
def test_invalid(content, filename):
    with pytest.raises(GuardError):
        parse_specification(content, filename, 10000)


@pytest.mark.parametrize(
    "ref", ["https://example.org/schema", "file:///etc/passwd", "other.yaml#/x"]
)
def test_external_refs_blocked(specification, ref):
    specification["components"] = {"schemas": {"Unsafe": {"$ref": ref}}}
    with pytest.raises(GuardError, match="Only local"):
        parse_specification(json.dumps(specification).encode(), "api.json", 10000)


def test_openapi31_and_internal_refs(engine, specification):
    specification["openapi"] = "3.1.0"
    specification["components"] = {"schemas": {"Item": {"type": ["string", "null"]}}}
    assert (
        parse_specification(json.dumps(specification).encode(), "api.json", 10000).openapi_version
        == "3.1.0"
    )
    assert engine.compare(specification, specification) == []


def test_cli_exit_codes(tmp_path, specification, engine, monkeypatch):
    monkeypatch.setenv("ACG_OASDIFF_PATH", engine.executable)
    base = tmp_path / "base.json"
    target = tmp_path / "target.json"
    base.write_text(json.dumps(specification))
    target.write_text(json.dumps({**specification, "paths": {}}))
    args = [
        sys.executable,
        "-m",
        "app.cli",
        "compare",
        "--base",
        str(base),
        "--target",
        str(target),
        "--format",
        "json",
    ]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 1, result.stderr
    assert json.loads(result.stdout)["summary"]["breaking"] > 0
    target.write_text(base.read_text())
    assert subprocess.run(args, capture_output=True).returncode == 0
    target.write_text("{")
    assert subprocess.run(args, capture_output=True).returncode == 2
