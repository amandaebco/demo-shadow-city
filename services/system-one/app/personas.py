"""Look up the stable parts of a persona (CONTRACT.md §2.1) from Firestore, cached per persona.

Only fields that do not change during a simulation are cached. Memory, which Track B
updates, already arrives in each request's context.
"""

import asyncio
import logging

logger = logging.getLogger("system-one")

STABLE_FIELDS = ("usual_mode", "vehicles", "income_band", "occupation")


class PersonaLookup:
    def __init__(self, firestore_client):
        self._db = firestore_client
        self._cache: dict[str, dict | None] = {}

    async def get(self, persona_id: str) -> dict | None:
        if persona_id not in self._cache:
            self._cache[persona_id] = await asyncio.to_thread(self._fetch, persona_id)
        return self._cache[persona_id]

    def _fetch(self, persona_id: str) -> dict | None:
        try:
            snapshot = self._db.collection("personas").document(persona_id).get()
            if not snapshot.exists:
                logger.warning("Persona %s not found; deciding without habit context", persona_id)
                return None
            data = snapshot.to_dict() or {}
            return {field: data.get(field) for field in STABLE_FIELDS}
        except Exception:
            logger.exception("Persona lookup failed for %s; deciding without habit context", persona_id)
            return None
