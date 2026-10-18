"""Scenario preparation: population ready -> scenario-start (CONTRACT.md §6)."""

import asyncio
import logging
from datetime import datetime, timezone

from app.clustering import cluster_personas
from app.models import ScenarioStatus
from app.population import build_skeletons, legacy_population_id_for, population_id_for

logger = logging.getLogger("orchestrator")

# Two scenarios with the same seed and size must not generate the same population at once.
_population_locks: dict[str, asyncio.Lock] = {}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def ensure_population(store, generator, seed: int, size: int) -> str:
    # A population from before the official reference data is reused as it is, so scenarios that
    # compare against an existing baseline keep the same residents.
    legacy_id = legacy_population_id_for(seed, size)
    if await asyncio.to_thread(store.count_personas, legacy_id) >= size:
        logger.info("Reusing population %s", legacy_id)
        return legacy_id
    population_id = population_id_for(seed, size)
    lock = _population_locks.setdefault(population_id, asyncio.Lock())
    async with lock:
        existing = await asyncio.to_thread(store.count_personas, population_id)
        if existing >= size:
            logger.info("Reusing population %s (%d personas)", population_id, existing)
            return population_id
        personas = [p.model_dump(mode="json") for p in await generator.generate(build_skeletons(seed, size))]
        # Layer 6: residents with similar profiles share one decision (CONTRACT.md §4.6).
        clusters = cluster_personas(personas, population_id)
        for persona in personas:
            persona.update(clusters[persona["persona_id"]])
        await asyncio.to_thread(store.write_personas, personas)
        logger.info("Generated population %s (%d personas)", population_id, len(personas))
        return population_id


async def prepare_scenario(scenario_id: str, store, generator, publisher) -> None:
    scenario = await asyncio.to_thread(store.get_scenario, scenario_id)
    try:
        await asyncio.to_thread(store.update_scenario, scenario_id, {
            "status": ScenarioStatus.generating_population.value, "updated_at": utc_now(),
        })
        population_id = await ensure_population(store, generator, scenario["seed"], scenario["population_size"])
        await asyncio.to_thread(store.update_scenario, scenario_id, {
            "population_id": population_id, "updated_at": utc_now(),
        })
        # Track B picks it up from here and sets status to running.
        await asyncio.to_thread(publisher.scenario_start, scenario_id, scenario["seed"])
    except Exception as exc:
        logger.exception("Preparing scenario %s failed", scenario_id)
        error = {"code": "INTERNAL", "message": str(exc)[:500]}
        await asyncio.to_thread(store.update_scenario, scenario_id, {
            "status": ScenarioStatus.failed.value, "updated_at": utc_now(),
        })
        try:
            await asyncio.to_thread(publisher.scenario_failed, scenario_id, "population", error)
        except Exception:
            logger.exception("Publishing scenario-failed for %s failed", scenario_id)
