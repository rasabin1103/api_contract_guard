"""Exercise the running HTTP service, including Swagger, without third-party dependencies."""

import argparse
import json
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base_url = args.url.rstrip("/")

    def request(
        path: str,
        method: str = "GET",
        body: bytes | None = None,
        content_type: str = "application/json",
    ) -> bytes:
        with urlopen(
            Request(
                base_url + path,
                data=body,
                method=method,
                headers={"Content-Type": content_type},
            ),
            timeout=75,
        ) as response:
            return response.read()

    def api(path: str, method: str = "GET", body: dict | None = None):
        data = request(path, method, json.dumps(body).encode() if body is not None else None)
        return json.loads(data) if data else None

    assert api("/health")["status"] == "ok"
    assert b"swagger-ui" in request("/docs")
    assert "/api/v1/projects" in api("/openapi.json")["paths"]
    # Estos ficheros son requests completos listos para copiar a Swagger/PowerShell.
    for filename, valid, count in [
        ("request-schema-invalid.json", False, 2),
        ("request-schema-valid.json", True, 0),
    ]:
        result = api(
            "/api/v1/validations/schema",
            "POST",
            json.loads((ROOT / "examples" / filename).read_text()),
        )
        assert result["valid"] is valid and result["error_count"] == count
    name = f"Contract Guard smoke {uuid4()}"
    project = api(
        "/api/v1/projects",
        "POST",
        {"name": name, "description": "Temporary verification"},
    )
    project_path = f"/api/v1/projects/{project['id']}"
    try:
        versions = []
        for label, filename in [
            ("v1", "openapi-v1.yaml"),
            ("v2", "openapi-v2-breaking.yaml"),
        ]:
            boundary = uuid4().hex
            body = (
                (
                    f'--{boundary}\r\nContent-Disposition: form-data; name="version_label"\r\n\r\n{label}\r\n'
                    f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                    "Content-Type: application/yaml\r\n\r\n"
                ).encode()
                + (ROOT / "examples" / filename).read_bytes()
                + f"\r\n--{boundary}--\r\n".encode()
            )
            versions.append(
                json.loads(
                    request(
                        project_path + "/contracts",
                        "POST",
                        body,
                        f"multipart/form-data; boundary={boundary}",
                    )
                )
            )
        assert len(api(project_path + "/contracts")) == 2
        report = api(
            project_path + "/comparisons",
            "POST",
            {"baseline_id": versions[0]["id"], "candidate_id": versions[1]["id"]},
        )
        assert report["summary"]["breaking"] == 4
        assert report["engine"]["version"] == "1.34.0"
        assert api(f"/api/v1/comparisons/{report['id']}/export") == report
        assert len(api(project_path + "/comparisons")) == 1
        validation_path = project_path + f"/contracts/{versions[0]['id']}/validate-response"
        captured = {
            "path": "/items",
            "method": "GET",
            "status_code": 200,
            "content_type": "application/json",
            "response_body": {"id": "123", "name": "Ana"},
        }
        invalid = api(validation_path, "POST", captured)
        assert invalid["valid"] is False and invalid["errors"][0]["path"] == "/id"
        captured["response_body"]["id"] = 123
        assert api(validation_path, "POST", captured)["valid"] is True
        standalone = api(
            "/api/v1/validations/schema",
            "POST",
            {"schema": {"type": "integer"}, "response_body": "123"},
        )
        assert standalone["valid"] is False
        for filename, expected in [
            ("response-valid.json", True),
            ("response-invalid.json", False),
        ]:
            boundary = uuid4().hex
            parts = []
            for field, source in [
                ("schema_file", "response-schema.json"),
                ("response_file", filename),
            ]:
                parts.append(
                    (
                        f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{source}"\r\n'
                        "Content-Type: application/json\r\n\r\n"
                    ).encode()
                    + (ROOT / "examples" / source).read_bytes()
                    + b"\r\n"
                )
            payload = b"".join(parts) + f"--{boundary}--\r\n".encode()
            uploaded = json.loads(
                request(
                    "/api/v1/validations/schema/files",
                    "POST",
                    payload,
                    f"multipart/form-data; boundary={boundary}",
                )
            )
            assert uploaded["valid"] is expected
        assert len(api(project_path + "/comparisons")) == 1
    finally:
        request(project_path + "?confirm_name=" + quote(name, safe=""), "DELETE")
    print(
        "PASS: Swagger, projects, imports, comparison, history, export, response validation and deletion"
    )


if __name__ == "__main__":
    main()
