"""Limites de entrada y errores HTTP comunes, sin registrar cuerpos ni secretos."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.domain.models import GuardError
from app.services.response_validation import parse_json_file


def configure_http(app: FastAPI, settings: Settings) -> None:
    """Registrar el perimetro HTTP antes de incluir las rutas de negocio."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
    )

    @app.middleware("http")
    async def upload_limit(request: Request, call_next):
        # Limitar tambien requests chunked antes de que el parser multipart cree temporales.
        is_validation = request.url.path.endswith(
            "/validate-response"
        ) or request.url.path.startswith("/api/v1/validations/")
        if request.method == "POST" and (request.url.path.endswith("/contracts") or is_validation):
            maximum = settings.max_upload_bytes + 64 * 1024
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > maximum:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "error": {
                                "code": "upload_too_large",
                                "message": "Upload exceeds size limit",
                            }
                        },
                    )
            # Starlette necesita reproducir el cuerpo ya consumido para formularios/Pydantic.
            request._body = bytes(body)
            media = (
                request.headers.get("content-type", "application/json")
                .split(";", 1)[0]
                .strip()
                .lower()
            )
            if is_validation and (
                media == "application/json"
                or (media.startswith("application/") and media.endswith("+json"))
            ):
                try:
                    parse_json_file(bytes(body), "request.json", settings.max_upload_bytes)
                except GuardError as exc:
                    return JSONResponse(
                        status_code=exc.status,
                        content={"error": {"code": exc.code, "message": exc.message}},
                    )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(GuardError)
    async def guard_error(_: Request, exc: GuardError):
        return JSONResponse(
            status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}}
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Invalid request",
                    "details": [
                        {"location": list(e["loc"]), "message": e["msg"]} for e in exc.errors()
                    ],
                }
            },
        )

    @app.exception_handler(IntegrityError)
    async def conflict(_: Request, __: IntegrityError):
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "duplicate_contract",
                    "message": "Version label or contract content already exists",
                }
            },
        )

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception):
        logging.getLogger("guard").error("Unhandled error type: %s", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={
                "error": {"code": "internal_error", "message": "An unexpected error occurred"}
            },
        )
