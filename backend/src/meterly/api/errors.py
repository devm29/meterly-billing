from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError

from meterly.errors import DomainError
from meterly.log import get_logger

log = get_logger(__name__)
_CONFLICTS = {
    "23514": ("constraint_violation", "the change conflicts with a billing invariant"),
    "23P01": ("constraint_violation", "the change overlaps an existing date range"),
    "23505": ("conflict", "resource already exists"),
}


def _body(code: str, message: str, details: object | None = None) -> dict[str, object]:
    error: dict[str, object] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = jsonable_encoder(
            [
                {"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")}
                for e in exc.errors()
            ]
        )
        return JSONResponse(
            _body("validation_error", "request did not pass validation", details), status_code=422
        )

    @app.exception_handler(DBAPIError)
    async def database_error(request: Request, exc: DBAPIError) -> JSONResponse:
        sqlstate = getattr(exc.orig, "sqlstate", None)
        if sqlstate in _CONFLICTS:
            # Constraint and trigger text names internal tables; keep it in the logs only.
            log.warning(
                "db.conflict", path=request.url.path, sqlstate=sqlstate, detail=str(exc.orig)
            )
            return JSONResponse(_body(*_CONFLICTS[sqlstate]), 409)
        log.exception("db.error", path=request.url.path)
        return JSONResponse(_body("database_error", "the database rejected the request"), 500)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled", path=request.url.path, error=type(exc).__name__)
        return JSONResponse(_body("internal_error", "something went wrong on our side"), 500)
