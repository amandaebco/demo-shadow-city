"""System One service: POST /v1/decide and GET /v1/health (CONTRACT.md §4)."""

import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.models import DecideRequest, DecideResponse
from app.rules import MODEL_VERSION, decide

logger = logging.getLogger("system-one")

app = FastAPI(title="Shadow City System One", version=MODEL_VERSION)

ERROR_CODES = {400: "INVALID_REQUEST", 404: "NOT_FOUND", 429: "RATE_LIMITED", 503: "MODEL_UNAVAILABLE"}


def error_response(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    """Error body as defined in CONTRACT.md §7."""
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {"loc": list(e.get("loc", [])), "msg": e.get("msg", "")} for e in exc.errors()
    ]
    return error_response(400, "INVALID_REQUEST", "Request body does not match the contract", jsonable_encoder({"errors": errors}))


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = ERROR_CODES.get(exc.status_code, "INTERNAL" if exc.status_code >= 500 else "INVALID_REQUEST")
    return error_response(exc.status_code, code, str(exc.detail))


@app.exception_handler(Exception)
async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error", exc_info=exc)
    return error_response(500, "INTERNAL", "Internal error")


@app.get("/v1/health")
def health() -> dict:
    return {"status": "ok", "model_version": MODEL_VERSION}


@app.post("/v1/decide", response_model=DecideResponse)
def decide_batch(request: DecideRequest) -> DecideResponse:
    # TODO(Layer 4): log every request + response to BigQuery (CONTRACT.md §2.3, §6).
    return DecideResponse(items=[decide(item) for item in request.items])
