import json
from uuid import uuid4


def create(client, name="Inventory"):
    response = client.post("/api/v1/projects", json={"name": name, "description": "Test API"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def upload(client, project, spec, label):
    return client.post(
        f"/api/v1/projects/{project}/contracts",
        data={"version_label": label},
        files={"file": ("api.json", json.dumps(spec), "application/json")},
    )


def test_project_crud(client):
    identifier = create(client)
    assert client.get("/health").status_code == 200
    assert len(client.get("/api/v1/projects").json()) == 1
    assert (
        client.patch(f"/api/v1/projects/{identifier}", json={"name": "Updated"}).json()["name"]
        == "Updated"
    )
    assert client.delete(f"/api/v1/projects/{identifier}?confirm_name=wrong").status_code == 409
    assert client.delete(f"/api/v1/projects/{identifier}?confirm_name=Updated").status_code == 204
    assert client.get(f"/api/v1/projects/{identifier}").status_code == 404


def test_swagger_entrypoint_and_import_schema(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/docs"
    assert "swagger-ui" in client.get("/docs").text
    schema = client.get("/openapi.json").json()
    assert "/" not in schema["paths"]
    upload_operation = schema["paths"]["/api/v1/projects/{project_id}/contracts"]["post"]
    assert "multipart/form-data" in upload_operation["requestBody"]["content"]
    assert "/api/v1/projects/{project_id}/comparisons" in schema["paths"]
    assert "/api/v1/comparisons/{comparison_id}/export" in schema["paths"]


def test_end_to_end_persistence_export_and_duplicates(client, specification):
    identifier = create(client)
    base_response = upload(client, identifier, specification, "v1")
    assert base_response.status_code == 201, base_response.text
    base = base_response.json()
    assert len(base["content_hash"]) == 64
    assert upload(client, identifier, specification, "duplicate").status_code == 409
    target_response = upload(client, identifier, {**specification, "paths": {}}, "v2")
    target = target_response.json()
    assert target_response.status_code == 201
    assert len(client.get(f"/api/v1/projects/{identifier}/contracts").json()) == 2
    stored = client.get(f"/api/v1/projects/{identifier}/contracts/{base['id']}").json()
    assert json.loads(stored["specification_content"]) == specification
    payload = {"baseline_id": base["id"], "candidate_id": target["id"]}
    response = client.post(f"/api/v1/projects/{identifier}/comparisons", json=payload)
    assert response.status_code == 201, response.text
    report = response.json()
    assert report["summary"]["breaking"] > 0
    assert report["engine"]["version"] == "1.34.0"
    comparison = report["id"]
    assert client.get(f"/api/v1/comparisons/{comparison}").json() == report
    export = client.get(f"/api/v1/comparisons/{comparison}/export")
    assert export.json() == report and "attachment" in export.headers["content-disposition"]
    assert len(client.get(f"/api/v1/projects/{identifier}/comparisons").json()) == 1
    repeated = client.post(f"/api/v1/projects/{identifier}/comparisons", json=payload).json()
    assert repeated["findings"] == report["findings"]
    other = create(client, "Other")
    assert client.post(f"/api/v1/projects/{other}/comparisons", json=payload).status_code == 404
    assert client.delete(f"/api/v1/projects/{identifier}?confirm_name=Inventory").status_code == 204
    assert client.get(f"/api/v1/comparisons/{comparison}").status_code == 404


def test_errors(client):
    assert client.post("/api/v1/projects", json={"name": " "}).status_code == 422
    assert client.get("/api/v1/projects/not-a-uuid").status_code == 422
    assert client.get(f"/api/v1/projects/{uuid4()}").status_code == 404
    assert client.get("/api/v1/projects?limit=999").status_code == 422
    identifier = create(client)
    response = client.post(
        f"/api/v1/projects/{identifier}/contracts",
        data={"version_label": "bad"},
        files={"file": ("bad.yaml", "openapi: invalid")},
    )
    assert response.status_code == 422 and "error" in response.json()
    oversized = client.post(
        f"/api/v1/projects/{identifier}/contracts",
        data={"version_label": "large"},
        files={"file": ("large.json", b"x" * (3 * 1024 * 1024))},
    )
    assert oversized.status_code == 413
