"""System One service: POST /v1/decide and GET /v1/health (CONTRACT.md §4)."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings, load_settings
from app.evidence import log_decision
from app.models import DecideRequest, DecideResponse, DecisionRequestItem, DecisionResponseItem
from app.rules import MODEL_VERSION, decide

logger = logging.getLogger("system-one")


class RuleDecider:
    """CONTRACT.md §4.4 mock."""

    model_version = MODEL_VERSION

    async def decide_batch(self, items: list[DecisionRequestItem]) -> list[DecisionResponseItem]:
        return [decide(item) for item in items]


def build_decider(settings: Settings):
    if settings.decider == "rule":
        return RuleDecider()
    if settings.decider == "gemini":
        # Imported lazily so the rule mock runs without Google Cloud credentials.
        from google import genai
        from google.cloud import firestore

        from app.gemini_decider import GeminiDecider
        from app.personas import PersonaLookup
        from app.seeds import SeedLookup

        client = genai.Client(vertexai=True, project=settings.project_id, location=settings.gemini_location)
        db = firestore.Client(project=settings.project_id, database=settings.firestore_database)
        decider = GeminiDecider(
            client, settings.gemini_model, settings.gemini_fallback_model, SeedLookup(db),
            settings.gemini_concurrency, PersonaLookup(db),
        )
        decider.model_version = settings.gemini_model
        return decider
    raise ValueError(f"Unknown DECIDER '{settings.decider}' (expected 'rule' or 'gemini')")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not hasattr(app.state, "decider"):
        app.state.decider = build_decider(load_settings())
    yield


app = FastAPI(title="Shadow City System One", lifespan=lifespan)

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
def health(request: Request) -> dict:
    return {"status": "ok", "model_version": request.app.state.decider.model_version}


@app.post("/v1/decide", response_model=DecideResponse)
async def decide_batch(body: DecideRequest, request: Request) -> DecideResponse:
    results = await request.app.state.decider.decide_batch(body.items)
    for item, result in zip(body.items, results):
        log_decision(item, result)
    return DecideResponse(items=results)
