# Engineering conventions

This is an independent product. Never import ASE platform code or require ASE services.
Keep parsing, domain findings and the engine adapter independent of HTTP and persistence.
Use Python 3.12+, typed Python, Pydantic 2 and SQLAlchemy 2.
This repository delivers an API service and CLI, without a product frontend or visual identity.
ASE owns the user-facing experience. Standalone testing uses FastAPI Swagger at /docs.
Never fetch references from uploaded documents. Invoke pinned oasdiff without a shell.
Use migrations for schema changes. Scope every version lookup to its project.
Do not claim checks passed unless executed. Keep deployment local by default.
Do not push, publish or deploy without explicit authorization.
