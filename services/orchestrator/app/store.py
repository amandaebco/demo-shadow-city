"""Firestore access (CONTRACT.md §5). Always the named database, never (default)."""

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

WRITE_BATCH_LIMIT = 500


class FirestoreStore:
    def __init__(self, client: firestore.Client):
        self._db = client

    def create_scenario(self, scenario: dict) -> None:
        self._db.collection("scenarios").document(scenario["scenario_id"]).create(scenario)

    def get_scenario(self, scenario_id: str) -> dict | None:
        snapshot = self._db.collection("scenarios").document(scenario_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    def list_scenarios(self, limit: int = 100) -> list[dict]:
        query = (
            self._db.collection("scenarios")
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        return [doc.to_dict() for doc in query.stream()]

    def update_scenario(self, scenario_id: str, fields: dict) -> None:
        self._db.collection("scenarios").document(scenario_id).update(fields)

    def get_metrics(self, scenario_id: str) -> dict | None:
        ref = self._db.collection("scenarios").document(scenario_id).collection("metrics").document("summary")
        snapshot = ref.get()
        return snapshot.to_dict() if snapshot.exists else None

    def get_persona(self, persona_id: str) -> dict | None:
        snapshot = self._db.collection("personas").document(persona_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    def count_personas(self, population_id: str) -> int:
        query = self._db.collection("personas").where(filter=FieldFilter("population_id", "==", population_id))
        result = query.count().get()
        return int(result[0][0].value)

    def write_personas(self, personas: list[dict]) -> None:
        collection = self._db.collection("personas")
        for start in range(0, len(personas), WRITE_BATCH_LIMIT):
            batch = self._db.batch()
            for persona in personas[start:start + WRITE_BATCH_LIMIT]:
                batch.set(collection.document(persona["persona_id"]), persona)
            batch.commit()
