"""Decision cache (CONTRACT.md §5, `decision_cache/{cache_key}`), Layer 2 determinism.

Gemini can answer the same prompt slightly differently, so without a cache the same
scenario would not replay identically. The key covers everything that shapes a decision
(model, seed, tick, persona, options, context) and excludes request_id, so an identical
request in any later run returns the stored decision without a model call.
"""

import asyncio
import hashlib
import json

from app.models import DecisionRequestItem

KEY_VERSION = 1
COLLECTION = "decision_cache"


def cache_key(item: DecisionRequestItem, seed: int, model: str) -> str:
    payload = {
        "v": KEY_VERSION,
        "model": model,
        "seed": seed,
        "tick": item.tick,
        "persona_id": item.persona_id,
        "question_type": item.question_type.value,
        "options": [o.value for o in item.options],
        "context": item.context.model_dump(mode="json"),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class FirestoreDecisionCache:
    def __init__(self, firestore_client):
        self._db = firestore_client

    async def get_many(self, keys: list[str]) -> dict[str, dict]:
        if not keys:
            return {}
        return await asyncio.to_thread(self._get_many, keys)

    def _get_many(self, keys: list[str]) -> dict[str, dict]:
        refs = [self._db.collection(COLLECTION).document(k) for k in dict.fromkeys(keys)]
        return {snap.id: snap.to_dict() for snap in self._db.get_all(refs) if snap.exists}

    async def put_many(self, entries: dict[str, dict]) -> None:
        if entries:
            await asyncio.to_thread(self._put_many, entries)

    def _put_many(self, entries: dict[str, dict]) -> None:
        items = list(entries.items())
        for start in range(0, len(items), 500):
            batch = self._db.batch()
            for key, value in items[start:start + 500]:
                batch.set(self._db.collection(COLLECTION).document(key), value)
            batch.commit()
