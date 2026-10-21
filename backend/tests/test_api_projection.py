"""Regresiones de las optimizaciones: conservar respuestas sin cargar contratos grandes."""

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import defer
from test_api import create, upload

from app.api.queries import contract_summary
from app.db.models import Contract


def test_metadata_serialization_never_reads_specification(client, specification):
    project = create(client)
    imported = upload(client, project, specification, "v1").json()
    with client.app.state.session_factory() as session:
        value = session.scalar(
            select(Contract).options(defer(Contract.specification_content, raiseload=True))
        )
        assert "specification_content" in inspect(value).unloaded
        assert contract_summary(value)["id"] == imported["id"]
        assert "specification_content" in inspect(value).unloaded


def test_contract_list_does_not_select_document_text(client, specification):
    project = create(client)
    upload(client, project, specification, "v1")
    statements = []

    def record_statement(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    database = client.app.state.database
    event.listen(database, "before_cursor_execute", record_statement)
    try:
        response = client.get(f"/api/v1/projects/{project}/contracts")
    finally:
        event.remove(database, "before_cursor_execute", record_statement)
    assert response.status_code == 200 and len(response.json()) == 1
    assert all("specification_content" not in statement for statement in statements)
