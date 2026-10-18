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

from app.backtest import evaluate_backtest
from app.config import Settings, load_settings
from app.models import ScenarioCreate, ScenarioStatus
from app.pipeline import prepare_scenario, utc_now
from app.report import report_id_for

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
    from app.report import ReportWriter
    from app.verifier import Verifier
    from app.store import FirestoreStore

    client = genai.Client(vertexai=True, project=settings.project_id, location=settings.gemini_location)
    return {
        "store": FirestoreStore(firestore.Client(project=settings.project_id, database=settings.firestore_database)),
        "generator": PersonaGenerator(client, settings.gemini_model),
        "report_writer": ReportWriter(client, settings.gemini_model),
        "verifier": Verifier(client, settings.gemini_model),
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


async def load_with_metrics(store, scenario_id: str) -> tuple[dict | None, dict | None]:
    scenario, metrics = await asyncio.gather(
        asyncio.to_thread(store.get_scenario, scenario_id), asyncio.to_thread(store.get_metrics, scenario_id)
    )
    return scenario, metrics


@app.get("/v1/scenarios/{scenario_id}/compare")
async def compare_scenarios(scenario_id: str, request: Request, base: str | None = None) -> dict:
    """CONTRACT.md §3: {"base": metrics, "variant": metrics}. `base` defaults to the scenario's baseline."""
    store = request.app.state.store
    variant, variant_metrics = await load_with_metrics(store, scenario_id)
    if not variant:
        raise not_found("Scenario", scenario_id)
    base_id = base or variant.get("base_scenario_id")
    if not base_id:
        raise ApiError(400, "INVALID_REQUEST", "No baseline: pass ?base={scenario_id}", {"field": "base"})
    base_scenario, base_metrics = await load_with_metrics(store, base_id)
    if not base_scenario:
        raise not_found("Scenario", base_id)
    if not variant_metrics or not base_metrics:
        missing = scenario_id if not variant_metrics else base_id
        raise ApiError(404, "NOT_FOUND", f"Metrics for scenario '{missing}' do not exist yet")
    return {"base": base_metrics, "variant": variant_metrics}


@app.get("/v1/scenarios/{scenario_id}/report")
async def get_report(scenario_id: str, request: Request) -> dict:
    """Analyst report. Layer 1: written on first request once Track B's metrics exist."""
    state = request.app.state
    report_id = report_id_for(scenario_id)
    report = await asyncio.to_thread(state.store.get_report, report_id)
    if report:
        return report
    scenario = await asyncio.to_thread(state.store.get_scenario, scenario_id)
    if not scenario:
        raise not_found("Scenario", scenario_id)
    metrics = await asyncio.to_thread(state.store.get_metrics, scenario_id)
    if not metrics:
        raise ApiError(404, "NOT_FOUND", f"Report for '{scenario_id}' is not available until its metrics exist")
    base_scenario = base_metrics = None
    if scenario.get("base_scenario_id"):
        base_scenario, base_metrics = await load_with_metrics(state.store, scenario["base_scenario_id"])
        if not base_metrics:
            raise ApiError(404, "NOT_FOUND", f"Report for '{scenario_id}' is not available until its baseline's metrics exist")
    counts = None
    if scenario.get("population_id"):
        counts = await asyncio.to_thread(state.store.home_counts, scenario["population_id"]) or None
    try:
        report = await state.report_writer.write(scenario, metrics, base_scenario, base_metrics, counts)
    except Exception as exc:
        logger.exception("Writing report for %s failed", scenario_id)
        raise ApiError(503, "MODEL_UNAVAILABLE", "Could not generate the report; retry later") from exc
    await asyncio.to_thread(state.store.save_report, report)
    return report


@app.get("/v1/scenarios/{scenario_id}/verification")
async def get_verification(scenario_id: str, request: Request) -> dict:
    """Verifier report (CONTRACT.md §2.6), generated on first request once metrics exist, then stored."""
    state = request.app.state
    report_id = f"r_verifier_{scenario_id.removeprefix('s_')}"
    stored = await asyncio.to_thread(state.store.get_report, report_id)
    if stored:
        return stored
    scenario, metrics = await load_with_metrics(state.store, scenario_id)
    if not scenario:
        raise not_found("Scenario", scenario_id)
    if not metrics or not scenario.get("population_id"):
        raise ApiError(404, "NOT_FOUND", f"Verification for '{scenario_id}' is not available until its metrics exist")
    personas = await asyncio.to_thread(state.store.personas_for, scenario["population_id"])
    report = await state.verifier.verify(scenario, metrics, personas)
    await asyncio.to_thread(state.store.save_report, report)
    return report


@app.get("/v1/backtests/{backtest_id}")
async def get_backtest(backtest_id: str, request: Request) -> dict:
    """Backtest result (CONTRACT.md §8), computed from the scenarios' current metrics."""
    store = request.app.state.store
    definition = await asyncio.to_thread(store.get_backtest, backtest_id)
    if not definition:
        raise not_found("Backtest", backtest_id)
    variant = await asyncio.to_thread(store.get_metrics, definition["scenario_id"]) if definition.get("scenario_id") else None
    base = await asyncio.to_thread(store.get_metrics, definition["base_scenario_id"]) if definition.get("base_scenario_id") else None
    return evaluate_backtest(definition, variant, base)


@app.get("/v1/personas/{persona_id}")
async def get_persona(persona_id: str, request: Request) -> dict:
    persona = await asyncio.to_thread(request.app.state.store.get_persona, persona_id)
    if not persona:
        raise not_found("Persona", persona_id)
    return persona
