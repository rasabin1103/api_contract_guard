import json
from time import monotonic
from unittest.mock import Mock

import pytest
from test_api import create, upload

from app.domain.models import GuardError
from app.services.response_validation import (
    MAX_ERRORS,
    run_validation,
    validate_json_schema,
    validate_openapi_response,
)


def validate(document, body, **overrides):
    options = dict(
        path="/items",
        method="GET",
        status_code=200,
        content_type="application/json",
        body_present=True,
    )
    options.update(overrides)
    return validate_openapi_response(document, response_body=body, **options)


def schema_node(document):
    return document["paths"]["/items"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]


def test_valid_and_invalid_types_are_not_coerced(specification):
    assert validate(specification, {"id": 123, "name": "Ana"})["valid"]
    result = validate(specification, {"id": "secret-bank-value", "name": "Ana"})
    assert not result["valid"]
    assert result["errors"][0]["path"] == "/id"
    assert result["errors"][0]["rule"] == "type"
    assert "secret-bank-value" not in json.dumps(result)
    assert validate(specification, {"id": True, "name": "Ana"})["valid"] is False


@pytest.mark.parametrize("version", ["3.0.3", "3.1.0"])
def test_refs_readonly_writeonly_and_required(specification, version):
    specification["openapi"] = version
    definition = {
        "type": "object",
        "required": ["id", "password"],
        "properties": {
            "id": {"type": "integer", "readOnly": True},
            "password": {"$ref": "#/components/schemas/Secret"},
        },
    }
    specification["components"] = {
        "schemas": {"Item": definition, "Secret": {"type": "string", "writeOnly": True}}
    }
    schema_node(specification).clear()
    schema_node(specification)["$ref"] = "#/components/schemas/Item"
    assert validate(specification, {"id": 123})["valid"]
    missing = validate(specification, {})
    assert missing["errors"][0]["path"] == "/id"
    assert not validate(specification, {"id": 123, "password": "sensitive"})["valid"]


@pytest.mark.parametrize("version", ["3.0.3", "3.1.0"])
def test_nullable_and_recursive_refs(specification, version):
    specification["openapi"] = version
    schema = schema_node(specification)
    schema.clear()
    schema.update({"$ref": "#/components/schemas/Node"})
    nullable = (
        {"type": "string", "nullable": True} if version == "3.0.3" else {"type": ["string", "null"]}
    )
    specification["components"] = {
        "schemas": {
            "Node": {
                "type": "object",
                "properties": {"name": nullable, "child": {"$ref": "#/components/schemas/Node"}},
            }
        }
    }
    assert validate(specification, {"name": None, "child": {"name": "x"}})["valid"]
    assert not validate(specification, {"name": 123})["valid"]


def test_concrete_paths_default_range_and_response_refs(specification):
    operation = specification["paths"].pop("/items")
    specification["paths"]["/items/{id}"] = operation
    response = operation["get"]["responses"].pop("200")
    specification["components"] = {
        "responses": {"Shared": response, "Alias": {"$ref": "#/components/responses/Shared"}}
    }
    operation["get"]["responses"]["2XX"] = {"$ref": "#/components/responses/Alias"}
    operation["get"]["responses"]["default"] = response
    result = validate(specification, {"id": 1, "name": "Ana"}, path="/items/123", status_code=201)
    assert result["valid"] and result["selection"]["response_key"] == "2XX"
    assert validate(specification, {"id": 1, "name": "Ana"}, path="/items/123", status_code=404)[
        "valid"
    ]


def test_path_item_refs(specification):
    specification["paths"]["/alias"] = {"$ref": "#/paths/~1items"}
    assert validate(specification, {"id": 1, "name": "Ana"}, path="/alias")["valid"]


def test_content_type_selection(specification):
    response = specification["paths"]["/items"]["get"]["responses"]["200"]
    response["content"]["application/*"] = response["content"].pop("application/json")
    assert validate(
        specification,
        {"id": 1, "name": "Ana"},
        content_type="application/problem+json; charset=utf-8",
    )["valid"]
    with pytest.raises(GuardError) as error:
        validate(specification, "x", content_type="text/xml")
    assert error.value.status == 415


def test_body_presence_and_no_schema_are_not_confused(specification):
    assert not validate(specification, None, body_present=False)["valid"]
    with pytest.raises(GuardError):
        validate(specification, {}, body_present=False)
    operation = specification["paths"]["/items"]["get"]
    operation["responses"]["204"] = {"description": "No content"}
    empty = validate(specification, None, status_code=204, body_present=False)
    assert empty["valid"] and empty["validation_scope"] == "body_presence_only"
    assert not validate(specification, None, status_code=204)["valid"]
    del operation["responses"]["200"]["content"]["application/json"]["schema"]
    with pytest.raises(GuardError, match="no schema"):
        validate(specification, {})


@pytest.mark.parametrize(
    "overrides", [{"path": "/missing"}, {"method": "POST"}, {"status_code": 404}]
)
def test_unknown_selectors(specification, overrides):
    with pytest.raises(GuardError):
        validate(specification, {}, **overrides)


def test_arrays_constraints_composition_formats_and_pointers():
    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "required": ["a/b~c"],
            "properties": {
                "a/b~c": {"allOf": [{"type": "integer"}, {"minimum": 1}]},
                "status": {"enum": ["active", "closed"]},
                "date": {"type": "string", "format": "date-time"},
            },
            "additionalProperties": False,
        },
    }
    result = validate_json_schema(
        schema, [{"a/b~c": 0, "status": "bad", "date": "not-date", "extra": 1}]
    )
    assert not result["valid"]
    assert {item["rule"] for item in result["errors"]} == {
        "minimum",
        "enum",
        "format",
        "additionalProperties",
    }
    assert any(item["path"] == "/0/a~1b~0c" for item in result["errors"])
    assert not validate_json_schema({"oneOf": [{"type": "integer"}, {"type": "string"}]}, False)[
        "valid"
    ]


def test_standalone_null_boolean_schemas_and_limit():
    assert validate_json_schema({"type": "null"}, None)["valid"]
    assert validate_json_schema(True, {"anything": 1})["valid"]
    assert not validate_json_schema(False, None)["valid"]
    result = validate_json_schema({"type": "array", "items": {"type": "integer"}}, ["x"] * 110)
    assert not result["valid"] and result["truncated"]
    assert result["error_count"] == MAX_ERRORS


@pytest.mark.parametrize(
    "schema",
    [
        {"$ref": "http://127.0.0.1/private"},
        {"$ref": "file:///etc/passwd"},
        {"$dynamicRef": "#/x"},
        {"$id": "https://example.test"},
        {"$schema": "http://json-schema.org/draft-07/schema#"},
    ],
)
def test_external_refs_and_unsupported_dialects(schema):
    with pytest.raises(GuardError):
        validate_json_schema(schema, {})


@pytest.mark.parametrize(
    "schema", [{"type": 123}, {"$ref": "#/missing"}, {"type": "string", "pattern": "["}]
)
def test_invalid_schemas_fail_not_pass(schema):
    with pytest.raises(GuardError, match="Schema could not be evaluated"):
        validate_json_schema(schema, {})


def test_timeout_worker_is_terminated(monkeypatch):
    context = Mock()
    context.Pipe.return_value = (Mock(), Mock())
    context.Pipe.return_value[0].poll.return_value = False
    process = context.Process.return_value
    process.pid = 123
    process.is_alive.return_value = True
    monkeypatch.setattr(
        "app.services.response_validation.multiprocessing.get_context", lambda _: context
    )
    with pytest.raises(GuardError) as error:
        run_validation({}, {}, "jsonschema202012", None, 1)
    assert error.value.status == 504
    process.terminate.assert_called_once()


def test_slow_regex_is_killed_by_real_timeout():
    started = monotonic()
    with pytest.raises(GuardError) as error:
        validate_json_schema({"type": "string", "pattern": "^(a+)+$"}, "a" * 32 + "!", timeout=1)
    assert error.value.status == 504
    assert monotonic() - started < 10


def test_cannot_mistake_openapi_for_an_unconstrained_schema(specification):
    with pytest.raises(GuardError, match="Import the OpenAPI"):
        validate_json_schema(specification, {})


def test_ambiguous_paths_require_template(specification):
    specification["paths"]["/{resource}/fixed"] = specification["paths"].pop("/items")
    specification["paths"]["/items/{id}"] = specification["paths"]["/{resource}/fixed"]
    with pytest.raises(GuardError, match="Ambiguous"):
        validate(specification, {}, path="/items/fixed")


def test_json_schema_document_has_local_defs():
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {"Item": {"type": "integer"}},
        "$ref": "#/$defs/Item",
    }
    assert validate_json_schema(schema, 123)["valid"]
    assert not validate_json_schema(schema, "123")["valid"]


def test_schema_api_and_uploads(client):
    schema = {"type": "object", "required": ["id"], "properties": {"id": {"type": "integer"}}}
    response = client.post(
        "/api/v1/validations/schema", json={"schema": schema, "response_body": {"id": "123"}}
    )
    assert response.status_code == 200, response.text
    assert response.json()["valid"] is False
    assert response.json()["errors"][0]["path"] == "/id"
    uploaded = client.post(
        "/api/v1/validations/schema/files",
        files={
            "schema_file": ("schema.json", json.dumps(schema)),
            "response_file": ("response.json", '{"id":123}'),
        },
    )
    assert uploaded.status_code == 200 and uploaded.json()["valid"]
    duplicate = client.post(
        "/api/v1/validations/schema/files",
        files={
            "schema_file": ("schema.json", json.dumps(schema)),
            "response_file": ("response.json", '{"id":1,"id":2}'),
        },
    )
    assert duplicate.status_code == 422
    raw = client.post(
        "/api/v1/validations/schema",
        content='{"schema":true,"response_body":NaN}',
        headers={"content-type": "application/json"},
    )
    assert raw.status_code == 422
    missing = client.post("/api/v1/validations/schema", json={"schema": True})
    assert missing.status_code == 422
    large = client.post("/api/v1/validations/schema", content=b" " * (3 * 1024 * 1024))
    assert large.status_code == 413


def test_saved_contract_validation_api_and_project_scope(client, specification):
    project = create(client)
    contract = upload(client, project, specification, "v1").json()
    route = f"/api/v1/projects/{project}/contracts/{contract['id']}/validate-response"
    body = {"path": "/items", "response_body": {"id": "123", "name": "Ana"}}
    result = client.post(route, json=body)
    assert result.status_code == 200, result.text
    assert not result.json()["valid"]
    assert result.json()["contract_id"] == contract["id"]
    assert result.json()["selection"]["path_template"] == "/items"
    other = create(client, "Other")
    assert client.post(route.replace(project, other), json=body).status_code == 404
    assert client.get(f"/api/v1/projects/{project}/comparisons").json() == []


def test_raw_json_duplicates_and_invalid_file_extension_are_rejected(client):
    duplicate = client.post(
        "/api/v1/validations/schema",
        content='{"schema":true,"schema":false,"response_body":1}',
        headers={"content-type": "application/json"},
    )
    assert duplicate.status_code == 422
    response = client.post(
        "/api/v1/validations/schema/files",
        files={
            "schema_file": ("schema.yaml", "type: integer"),
            "response_file": ("response.json", "123"),
        },
    )
    assert response.status_code == 415


@pytest.mark.parametrize("content_type", [None, "APPLICATION/JSON", "application/vnd.test+json"])
def test_duplicate_checks_cannot_be_bypassed_by_content_type(client, content_type):
    headers = {} if content_type is None else {"content-type": content_type}
    response = client.post(
        "/api/v1/validations/schema",
        headers=headers,
        content='{"schema":true,"schema":false,"response_body":1}',
    )
    assert response.status_code == 422


def test_standalone_openapi_rejection_and_required_null(client, specification):
    response = client.post(
        "/api/v1/validations/schema", json={"schema": specification, "response_body": {}}
    )
    assert response.status_code == 422
    response = client.post(
        "/api/v1/validations/schema", json={"schema": {"type": "null"}, "response_body": None}
    )
    assert response.status_code == 200 and response.json()["valid"]


@pytest.mark.parametrize("name", ["$schema", "$ref", "$id", "properties"])
def test_schema_keyword_names_are_ordinary_property_names(name):
    schema = {"type": "object", "properties": {name: {"type": "integer"}}, "required": [name]}
    assert validate_json_schema(schema, {name: 123})["valid"]
    result = validate_json_schema(schema, {name: "123"})
    assert not result["valid"]
    assert result["errors"][0]["path"] == "/" + name


def test_malformed_dialect_is_a_validation_error_not_a_server_error(client):
    response = client.post(
        "/api/v1/validations/schema", json={"schema": {"$schema": {}}, "response_body": 1}
    )
    assert response.status_code == 422
