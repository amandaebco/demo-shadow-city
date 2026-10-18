"""System One service: POST /v1/decide and GET /v1/health (CONTRACT.md §4)."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings, load_settings
from app.decision_log import BigQueryDecisionLog, decision_row
from app.evidence import log_decision
from app.models import DecideRequest, DecideResponse, DecisionRequestItem
from app.outcome import Outcome
from app.rules import MODEL_VERSION, decide

logger = logging.getLogger("system-one")


class RuleDecider:
    """CONTRACT.md §4.4 mock."""

    model_version = MODEL_VERSION

    async def decide_batch(self, items: list[DecisionRequestItem]) -> list[Outcome]:
        return [Outcome(decide(item), None, "off") for item in items]


def build_gemma(settings: Settings):
    if not settings.gemma_url:
        raise ValueError("DECIDER=gemma needs GEMMA_URL")
    from app.gemma import IdTokenProvider, OllamaGemma

    return OllamaGemma(settings.gemma_url, settings.gemma_model, IdTokenProvider(settings.gemma_url))


def build_decider(settings: Settings):
    if settings.decider == "rule":
        return RuleDecider()
    if settings.decider in ("gemini", "gemma"):
        # Imported lazily so the rule mock runs without Google Cloud credentials.
        from google import genai
        from google.cloud import firestore

        from app.cache import FirestoreDecisionCache
        from app.gemini_decider import GeminiDecider
        from app.personas import PersonaLookup
        from app.seeds import SeedLookup

        client = genai.Client(vertexai=True, project=settings.project_id, location=settings.gemini_location)
        db = firestore.Client(project=settings.project_id, database=settings.firestore_database)
        decider = GeminiDecider(
            client, settings.gemini_model, settings.gemini_fallback_model, SeedLookup(db),
            settings.gemini_concurrency, PersonaLookup(db),
            cache=FirestoreDecisionCache(db) if settings.decision_cache else None,
            primary=build_gemma(settings) if settings.decider == "gemma" else None,
            thinking_level=settings.gemini_thinking_level,
        )
        return decider
    raise ValueError(f"Unknown DECIDER '{settings.decider}' (expected 'rule', 'gemini' or 'gemma')")


def build_decision_log(settings: Settings):
    if not settings.bigquery_dataset:
        return None
    from google.cloud import bigquery

    client = bigquery.Client(project=settings.project_id)
    return BigQueryDecisionLog(client, f"{settings.project_id}.{settings.bigquery_dataset}.decisions")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    if not hasattr(app.state, "decider"):
        app.state.decider = build_decider(settings)
    if not hasattr(app.state, "decision_log"):
        app.state.decision_log = build_decision_log(settings)
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
    state = request.app.state
    outcomes = await state.decider.decide_batch(body.items)
    for item, outcome in zip(body.items, outcomes):
        log_decision(item, outcome.response, outcome.usage, outcome.cache)
    if state.decision_log is not None:
        rows = [decision_row(item, o.response, o.usage, o.cache) for item, o in zip(body.items, outcomes)]
        # Written before responding: Cloud Run throttles CPU after a response, so a background
        # write could stall or be lost when the instance scales down. Failures are only logged.
        await asyncio.to_thread(state.decision_log.write, rows)
    return DecideResponse(items=[outcome.response for outcome in outcomes])
