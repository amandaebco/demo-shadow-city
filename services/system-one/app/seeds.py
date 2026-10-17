"""Look up a scenario's seed from Firestore, cached per scenario."""

import asyncio
import logging

from app.sampling import scenario_seed_fallback

logger = logging.getLogger("system-one")


class SeedLookup:
    def __init__(self, firestore_client):
        self._db = firestore_client
        self._cache: dict[str, int] = {}

    async def get(self, scenario_id: str) -> int:
        if scenario_id in self._cache:
            return self._cache[scenario_id]
        seed = await asyncio.to_thread(self._fetch, scenario_id)
        self._cache[scenario_id] = seed
        return seed

    def _fetch(self, scenario_id: str) -> int:
        try:
            snapshot = self._db.collection("scenarios").document(scenario_id).get()
            if snapshot.exists and isinstance(snapshot.get("seed"), int):
                return snapshot.get("seed")
            logger.warning("Scenario %s has no seed in Firestore; using a hash of its ID", scenario_id)
        except Exception:
            logger.exception("Seed lookup failed for %s; using a hash of its ID", scenario_id)
        return scenario_seed_fallback(scenario_id)
