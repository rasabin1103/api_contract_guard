import copy
import json

import pytest
from test_api import create, upload


@pytest.mark.parametrize("scope", ["root", "path", "operation"])
@pytest.mark.parametrize("change", ["add", "remove", "url", "description", "variable"])
def test_server_changes_need_review(engine, specification, scope, change):
    base = copy.deepcopy(specification)
    target = copy.deepcopy(base)

    def node(document):
        if scope == "root":
            return document
        path = document["paths"]["/items"]
        return path if scope == "path" else path["get"]

    server = {
        "url": "https://{region}.example.test",
        "description": "Primary",
        "variables": {"region": {"default": "eu", "enum": ["eu", "us"]}},
    }
    node(base)["servers"] = [copy.deepcopy(server)]
    node(target)["servers"] = [copy.deepcopy(server)]
    if change == "add":
        del node(base)["servers"]
    elif change == "remove":
        del node(target)["servers"]
    elif change == "url":
        node(target)["servers"][0]["url"] = "https://new.example.test"
    elif change == "description":
        node(target)["servers"][0]["description"] = "Updated documentation"
    else:
        node(target)["servers"][0]["variables"]["region"]["default"] = "us"
    findings = [f for f in engine.compare(base, target) if f.category == "servers"]
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == (
        "informational" if change == "description" else "potentially_breaking"
    )
    assert finding.previous_value == node(base).get("servers")
    assert finding.current_value == node(target).get("servers")
    assert finding.engine_metadata["source"] == "oasdiff diff"
    assert (
        findings[0].to_dict()
        == [f for f in engine.compare(base, target) if f.category == "servers"][0].to_dict()
    )


def test_servers_in_report_and_export(client, specification):
    project = create(client)
    target = {**specification, "servers": [{"url": "/api/v3"}]}
    baseline = upload(client, project, specification, "v1").json()
    candidate = upload(client, project, target, "v2").json()
    response = client.post(
        f"/api/v1/projects/{project}/comparisons",
        json={"baseline_id": baseline["id"], "candidate_id": candidate["id"]},
    )
    assert response.status_code == 201, response.text
    report = response.json()
    assert report["overall_result"] == "review_required"
    assert report["summary"]["potentially_breaking"] == 1
    assert report["findings"][0]["current_value"] == [{"url": "/api/v3"}]
    assert report["engine_configuration"]["adapter_version"] == "2"
    assert client.get(f"/api/v1/comparisons/{report['id']}/export").json() == report


def test_server_order_is_not_a_semantic_change(engine, specification):
    base = {**specification, "servers": [{"url": "https://a.test"}, {"url": "https://b.test"}]}
    target = {**base, "servers": list(reversed(base["servers"]))}
    assert not [f for f in engine.compare(base, target) if f.category == "servers"]


def test_invalid_diff_is_not_silently_ignored(engine, specification, monkeypatch):
    from app.domain.models import GuardError

    results = iter(["oasdiff version 1.34.0", "[]", json.dumps([])])
    monkeypatch.setattr(engine, "_run", lambda *args: next(results))
    target = {**specification, "servers": [{"url": "/api/v3"}]}
    with pytest.raises(GuardError, match="Invalid comparison engine response"):
        engine.compare(specification, target)
