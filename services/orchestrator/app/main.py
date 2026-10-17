"""Orchestrator service (CONTRACT.md §3)."""

import asyncio
import logging
import re
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings, load_settings
from app.models import ScenarioCreate, ScenarioStatus
from app.pipeline import prepare_scenario, utc_now

SERVICE_VERSION = "0.2.0"

logger = logging.getLogger("orchestrator")

ERROR_CODES = {400: "INVALID_REQUEST", 404: "NOT_FOUND", 429: "RATE_LIMITED", 503: "MODEL_UNAVAILABLE"}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        self.status, self.code, self.message, self.details = status, code, message, details or {}


def build_dependencies(settings: Settings) -> dict:
    # Imported lazily so tests can inject fakes without Google Cloud credentials.
    from google import genai
    from google.cloud import firestore

    from app.events import PubSubPublisher
    from app.population import PersonaGenerator
    from app.store import FirestoreStore

    client = genai.Client(vertexai=True, project=settings.project_id, location=settings.gemini_location)
    return {
        "store": FirestoreStore(firestore.Client(project=settings.project_id, database=settings.firestore_database)),
        "generator": PersonaGenerator(client, settings.gemini_model),
        "publisher": PubSubPublisher(settings.project_id, settings.topic_scenario_start, settings.topic_scenario_failed),
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not hasattr(app.state, "store"):
        for name, dependency in build_dependencies(load_settings()).items():
            setattr(app.state, name, dependency)
    app.state.tasks = set()
    yield


app = FastAPI(title="Shadow City Orchestrator", version=SERVICE_VERSION, lifespan=lifespan)


def error_response(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    """Error body as defined in CONTRACT.md §7."""
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


@app.exception_handler(ApiError)
async def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc.status, exc.code, exc.message, exc.details)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    code = "INVALID_SCENARIO" if request.url.path == "/v1/scenarios" else "INVALID_REQUEST"
    first = errors[0] if errors else {}
    field = ".".join(str(p) for p in first.get("loc", [])[1:]) or None
    message = f"{field}: {first.get('msg')}" if field else "Request body does not match the contract"
    details = {"field": field, "errors": [{"loc": list(e.get("loc", [])), "msg": e.get("msg", "")} for e in errors]}
    return error_response(400, code, message, jsonable_encoder(details))


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = ERROR_CODES.get(exc.status_code, "INTERNAL" if exc.status_code >= 500 else "INVALID_REQUEST")
    return error_response(exc.status_code, code, str(exc.detail))


@app.exception_handler(Exception)
async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error", exc_info=exc)
    return error_response(500, "INTERNAL", "Internal error")


def new_scenario_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40] or "scenario"
    return f"s_{slug}_{uuid.uuid4().hex[:6]}"


def not_found(what: str, identifier: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", f"{what} '{identifier}' not found")


@app.get("/v1/health")
def health() -> dict:
    return {"status": "ok", "service": "orchestrator", "version": SERVICE_VERSION}


@app.post("/v1/scenarios", status_code=201)
async def create_scenario(body: ScenarioCreate, request: Request) -> dict:
    state = request.app.state
    if body.base_scenario_id and not await asyncio.to_thread(state.store.get_scenario, body.base_scenario_id):
        raise ApiError(400, "INVALID_SCENARIO", f"base_scenario_id '{body.base_scenario_id}' does not exist",
                       {"field": "base_scenario_id"})
    now = utc_now()
    scenario = {
        **body.model_dump(mode="json"),
        "scenario_id": new_scenario_id(body.name),
        "status": ScenarioStatus.queued.value,
        "progress": {"current_tick": 0, "total_ticks": 204},
        "created_at": now,
        "updated_at": now,
    }
    await asyncio.to_thread(state.store.create_scenario, scenario)
    # Runs after the response; Cloud Run must not throttle CPU (see infra/deploy.sh).
    task = asyncio.create_task(prepare_scenario(scenario["scenario_id"], state.store, state.generator, state.publisher))
    state.tasks.add(task)
    task.add_done_callback(state.tasks.discard)
    return {"scenario_id": scenario["scenario_id"]}


@app.get("/v1/scenarios")
async def list_scenarios(request: Request) -> list[dict]:
    return await asyncio.to_thread(request.app.state.store.list_scenarios)


@app.get("/v1/scenarios/{scenario_id}")
async def get_scenario(scenario_id: str, request: Request) -> dict:
    scenario = await asyncio.to_thread(request.app.state.store.get_scenario, scenario_id)
    if not scenario:
        raise not_found("Scenario", scenario_id)
    return scenario


@app.get("/v1/scenarios/{scenario_id}/metrics")
async def get_metrics(scenario_id: str, request: Request) -> dict:
    metrics = await asyncio.to_thread(request.app.state.store.get_metrics, scenario_id)
    if not metrics:
        raise not_found("Metrics for scenario", scenario_id)
    return metrics


@app.get("/v1/personas/{persona_id}")
async def get_persona(persona_id: str, request: Request) -> dict:
    persona = await asyncio.to_thread(request.app.state.store.get_persona, persona_id)
    if not persona:
        raise not_found("Persona", persona_id)
    return persona
