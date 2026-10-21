# REST API

Base URL: `http://127.0.0.1:8000/api/v1`. Interactive schema: `/docs`; schema JSON: `/openapi.json`.

| Method | Route | Input / behavior |
|---|---|---|
| GET | `/health` (outside prefix) | Database liveness, local mode and expected engine version |
| GET / POST | `/projects` | List or create `{name, description}`; creation returns 201 |
| GET / PATCH | `/projects/{uuid}` | Details or partial update |
| DELETE | `/projects/{uuid}?confirm_name=…` | Exact current name required; returns 204 |
| GET / POST | `/projects/{uuid}/contracts` | List or multipart `version_label` and `file`; returns 201 |
| GET | `/projects/{uuid}/contracts/{version_uuid}` | Includes original specification text |
| GET / POST | `/projects/{uuid}/comparisons` | History or `{baseline_id, candidate_id}`; returns complete report, 201 |
| GET | `/comparisons/{uuid}` | Complete stored report |
| GET | `/comparisons/{uuid}/export` | Complete JSON report, attachment filename |
| POST | `/projects/{uuid}/contracts/{version_uuid}/validate-response` | Captured JSON body and operation/status/media selectors; stateless |
| POST | `/validations/schema` | `{schema, response_body}`; standalone JSON Schema 2020-12, stateless |
| POST | `/validations/schema/files` | Multipart `schema_file` + `response_file`, both JSON, stateless |

All list endpoints accept `offset` (>=0) and `limit` (1–200, default 50). They return arrays ordered newest-first with ID tie breakers. Continue until fewer than `limit` records are returned.

Errors use `{"error":{"code":"validation_error","message":"…"}}`; request validation may include field locations and messages. Common statuses: 404 missing resource, 409 duplicate content/label or wrong deletion confirmation, 413 upload too large, 415 unsupported extension, 422 invalid contract/request or engine rejection, 503 unavailable/wrong engine and 504 engine timeout. Arbitrary unexpected errors return a generic 500 without exception details.

```sh
curl -X POST http://127.0.0.1:8000/api/v1/projects \
  -H 'Content-Type: application/json' -d '{"name":"Inventory","description":"Stock API"}'
curl -X POST http://127.0.0.1:8000/api/v1/projects/PROJECT_UUID/contracts \
  -F 'version_label=v1' -F 'file=@examples/openapi-v1.yaml'
curl -X POST http://127.0.0.1:8000/api/v1/projects/PROJECT_UUID/comparisons \
  -H 'Content-Type: application/json' \
  -d '{"baseline_id":"BASE_UUID","candidate_id":"CANDIDATE_UUID"}'
```

Reports include current project metadata and immutable version metadata, overall result, severity counts, engine version/configuration, timestamp and findings. Renaming a project is reflected when its historical reports are retrieved. An overall `compatible` means no breaking/warning rules fired under supported coverage. It is not proof of behavioral compatibility. Finding before/after values are source-operation context. ASE can filter and present the returned findings within its own interface. Exports always contain the complete stored report.

Health verifies the database connection but does not run a comparison or assert that migrations/engine are ready. Missing schema is surfaced by normal API requests; run migrations before startup. Missing/wrong engine is surfaced on comparison.

Adapter version 2 supplements changelog findings with semantic `servers` deltas from `oasdiff diff` at document, path and operation scope. The local rule `acg-server-configuration-changed` is marked `potentially_breaking` for configuration changes, or `informational` for description-only edits. These findings include actual server values and raw diff metadata. `summary.total` counts supported findings, not every document difference. Existing comparison runs retain their stored results; rerun to use the new configuration.

## Captured response validation (0.2.0)

For an imported OpenAPI contract, send `path`, `method` (default GET), `status_code` (default 200), `content_type` (default application/json), required `response_body` (any JSON value), and `body_present` (default true). `path` may be an exact template or an unambiguous concrete path. Status matching is exact, then status class (`2XX`), then default. Media selection is exact, then a declared type wildcard, then `*/*`. Only JSON bodies are evaluated. Body-absent responses use `response_body:null, body_present:false`; null alone is actual JSON data. Method/status body prohibitions and declared absence are checked explicitly.

Standalone input uses JSON Schema 2020-12 (object or boolean). The files endpoint takes two `.json` uploads. Both modes reject external refs, identities/anchors, dynamic refs and unsupported dialects. An OpenAPI document in the standalone schema field is rejected: import it as a contract instead.

HTTP **200** means evaluation succeeded; inspect **`valid`** to distinguish conforming and nonconforming data. Each error has JSON Pointer `path`, `schema_path`, `rule` and sanitized `message`. `error_count` is the returned count (max 100); `truncated` indicates additional errors. `selection` records the matched operation/status/media/schema for saved contracts. `validator` records library/version/dialect. `validation_scope=body_presence_only` explicitly means no schema was evaluated. Missing response schema or unsupported selection produces 422/404/415 rather than a false success. Timeout is 504; both per-process validation slots being occupied yields 503.

Responses and validation results are never inserted into comparison history or stored by this feature. No response values are echoed in error messages; field paths still contain property names and should be treated as sensitive metadata where applicable. No remote API calls, token handling, HTTP-header validation, cookie checks or latency measurements are performed. Known library formats are asserted; unknown/custom formats are annotations, reported as a warning. JSON Schema defaults are not injected and numeric strings are not coerced.
