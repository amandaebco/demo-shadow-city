"""Synthetic population generation (REFERENCE.md §6.1).

Two steps:
1. Deterministic skeleton from the scenario seed: home/work kelurahan and coordinates,
   age, income band. Same seed + size -> same skeletons.
2. Gemini fills in the behavioral profile: occupation, vehicles, usual mode,
   usual departure tick, cost/time sensitivity, and a one-line summary.

Gemini output is not bit-for-bit reproducible, so a population is generated once,
stored under its population_id, and reused by every scenario with the same seed and size.
"""

import asyncio
import json
import logging
import random

from google.genai import types

from app.costs import log_usage, usage_from_response
from app.kelurahan import AGE_BINS, AGE_COUNTS, HOME_KELURAHAN, HOME_WEIGHTS, WORK_KELURAHAN
from app.models import LAST_TICK, IncomeBand, Mode, Persona

logger = logging.getLogger("orchestrator")

BATCH_SIZE = 25
MAX_PARALLEL_BATCHES = 16  # 5,000 residents = 200 batches; avoid hitting Gemini rate limits
COORD_JITTER_DEG = 0.004
OWNED_VEHICLES = {Mode.motorcycle, Mode.car}

SYSTEM_INSTRUCTION = (
    "You create synthetic but realistic residents of Jakarta for a transport-policy simulator. "
    "For each resident skeleton you receive (home, work, age, income band), invent a plausible "
    "occupation, the private vehicles they own (motorcycle, car, or none), their usual commute "
    "mode, their usual departure tick (tick 0 = 05:00, 5 minutes per tick, most commuters leave "
    "between ticks 12 and 48), cost and time sensitivity between 0 and 1, and a one-sentence "
    "English profile summary under 160 characters. Keep the set diverse and consistent with "
    "income. Do not invent statistics."
)


# Populations built with official population weights carry this suffix; earlier populations
# (pop_s{seed}_n{size}) were drawn uniformly and are still reused as they are.
REFERENCE_VERSION = "r2"


def population_id_for(seed: int, size: int) -> str:
    return f"pop_s{seed}_n{size}_{REFERENCE_VERSION}"


def legacy_population_id_for(seed: int, size: int) -> str:
    return f"pop_s{seed}_n{size}"


def sample_age(rng: random.Random, kelurahan: str) -> int:
    """Age 18-64 from the kelurahan's official 5-year working-age bins."""
    counts = AGE_COUNTS.get(kelurahan)
    if not counts or not sum(counts.values()):
        return rng.randint(18, 64)
    weights = []
    for label in AGE_BINS:
        low = int(label.split()[0])
        # The 15-19 bin only contributes its 18-19 part.
        weights.append(counts[label] * (2 / 5 if low == 15 else 1))
    label = rng.choices(AGE_BINS, weights=weights)[0]
    low = int(label.split()[0])
    return rng.randint(max(18, low), low + 4)


def persona_id_for(population_id: str, index: int) -> str:
    return f"p_{population_id.removeprefix('pop_')}_{index:05d}"


def cluster_id_for(population_id: str, index: int) -> str:
    # Placeholder singleton cluster; app.clustering assigns real clusters before personas are stored.
    return f"c_{population_id.removeprefix('pop_')}_{index:05d}"


def _place(rng: random.Random, kelurahan: tuple) -> dict:
    name, _kecamatan, lat, lng = kelurahan
    return {
        "kelurahan": name,
        "lat": round(lat + rng.uniform(-COORD_JITTER_DEG, COORD_JITTER_DEG), 5),
        "lng": round(lng + rng.uniform(-COORD_JITTER_DEG, COORD_JITTER_DEG), 5),
    }


def build_skeletons(seed: int, size: int) -> list[dict]:
    """Deterministic part of each persona.

    Home kelurahan is weighted by official population and age follows that kelurahan's official
    working-age structure (app/kelurahan.py). TODO(data): income and workplace are placeholders.
    """
    rng = random.Random(seed)
    population_id = population_id_for(seed, size)
    income_bands = list(IncomeBand)
    skeletons = []
    for index in range(size):
        home = rng.choices(HOME_KELURAHAN, weights=HOME_WEIGHTS)[0]
        skeletons.append({
            "persona_id": persona_id_for(population_id, index),
            "cluster_id": cluster_id_for(population_id, index),
            "population_id": population_id,
            "home": _place(rng, home),
            "work": _place(rng, rng.choice(WORK_KELURAHAN)),
            "age": sample_age(rng, home[0]),
            "income_band": rng.choice(income_bands).value,
        })
    return skeletons


def profile_schema() -> dict:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "index": {"type": "integer"},
                "occupation": {"type": "string"},
                "vehicles": {"type": "array", "items": {"type": "string", "enum": ["motorcycle", "car"]}},
                "usual_mode": {"type": "string", "enum": [m.value for m in Mode]},
                "usual_departure_tick": {"type": "integer"},
                "cost_sensitivity": {"type": "number"},
                "time_sensitivity": {"type": "number"},
                "profile_summary": {"type": "string"},
            },
            "required": [
                "index", "occupation", "vehicles", "usual_mode", "usual_departure_tick",
                "cost_sensitivity", "time_sensitivity", "profile_summary",
            ],
        },
    }


def _clamp(value, lo, hi, default):
    try:
        return min(hi, max(lo, type(default)(value)))
    except (TypeError, ValueError):
        return default


def merge_profile(skeleton: dict, profile: dict) -> Persona:
    """Combine a skeleton with Gemini's profile, repairing out-of-range or inconsistent values."""
    vehicles = [Mode(v) for v in dict.fromkeys(profile.get("vehicles") or []) if v in {"motorcycle", "car"}]
    usual_mode = Mode(profile["usual_mode"])
    if usual_mode in OWNED_VEHICLES and usual_mode not in vehicles:
        vehicles.append(usual_mode)  # Keep the persona consistent: you ride what you own.
    return Persona(
        **skeleton,
        occupation=str(profile.get("occupation") or "resident")[:80],
        vehicles=vehicles,
        usual_mode=usual_mode,
        usual_departure_tick=_clamp(profile.get("usual_departure_tick"), 0, LAST_TICK, 24),
        cost_sensitivity=_clamp(profile.get("cost_sensitivity"), 0.0, 1.0, 0.5),
        time_sensitivity=_clamp(profile.get("time_sensitivity"), 0.0, 1.0, 0.5),
        profile_summary=str(profile.get("profile_summary") or "")[:200],
        memory=[],
    )


class PersonaGenerator:
    def __init__(self, client, model: str, max_attempts: int = 2):
        self._client = client
        self._model = model
        self._max_attempts = max_attempts
        self._parallel = asyncio.Semaphore(MAX_PARALLEL_BATCHES)

    async def generate(self, skeletons: list[dict]) -> list[Persona]:
        batches = [skeletons[i:i + BATCH_SIZE] for i in range(0, len(skeletons), BATCH_SIZE)]
        async def limited(batch):
            async with self._parallel:
                return await self._generate_batch(batch)

        results = await asyncio.gather(*(limited(b) for b in batches))
        return [persona for batch in results for persona in batch]

    async def _generate_batch(self, skeletons: list[dict]) -> list[Persona]:
        pending = dict(enumerate(skeletons))
        personas: dict[int, Persona] = {}
        for attempt in range(1, self._max_attempts + 1):
            try:
                profiles = await self._ask(pending)
            except Exception:
                logger.exception("Gemini persona call failed (attempt %d)", attempt)
                profiles = []
            for profile in profiles:
                index = profile.get("index")
                if index in pending:
                    try:
                        personas[index] = merge_profile(pending[index], profile)
                    except (KeyError, ValueError) as exc:
                        logger.warning("Discarding invalid profile %s: %s", index, exc)
            pending = {i: s for i, s in pending.items() if i not in personas}
            if not pending:
                break
            logger.warning("Attempt %d left %d personas without a profile", attempt, len(pending))
        if pending:
            raise RuntimeError(f"Gemini did not return valid profiles for {len(pending)} personas")
        return [personas[i] for i in sorted(personas)]

    async def _ask(self, pending: dict[int, dict]) -> list[dict]:
        lines = []
        for index, s in pending.items():
            lines.append(json.dumps({
                "index": index,
                "home_kelurahan": s["home"]["kelurahan"],
                "work_kelurahan": s["work"]["kelurahan"],
                "age": s["age"],
                "income_band": s["income_band"],
            }))
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents="Resident skeletons (one JSON object per line):\n" + "\n".join(lines),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.7,
                response_mime_type="application/json",
                response_schema=profile_schema(),
            ),
        )
        population_id = next(iter(pending.values()))["population_id"]
        log_usage("population", usage_from_response(self._model, response), population_id=population_id)
        parsed = json.loads(response.text)
        return parsed if isinstance(parsed, list) else []
