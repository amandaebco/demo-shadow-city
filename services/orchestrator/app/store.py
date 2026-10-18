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

    def get_report(self, report_id: str) -> dict | None:
        snapshot = self._db.collection("reports").document(report_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    def save_report(self, report: dict) -> None:
        self._db.collection("reports").document(report["report_id"]).set(report)

    def get_persona(self, persona_id: str) -> dict | None:
        snapshot = self._db.collection("personas").document(persona_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    def count_personas(self, population_id: str) -> int:
        query = self._db.collection("personas").where(filter=FieldFilter("population_id", "==", population_id))
        result = query.count().get()
        return int(result[0][0].value)

    def home_counts(self, population_id: str) -> dict[str, int]:
        """Residents per home kelurahan in a population."""
        query = (
            self._db.collection("personas")
            .where(filter=FieldFilter("population_id", "==", population_id))
            .select(["home.kelurahan"])
        )
        counts: dict[str, int] = {}
        for doc in query.stream():
            name = (doc.to_dict().get("home") or {}).get("kelurahan")
            if name:
                counts[name] = counts.get(name, 0) + 1
        return counts

    def personas_for(self, population_id: str) -> list[dict]:
        """Every persona in a population, ordered by persona_id."""
        query = self._db.collection("personas").where(filter=FieldFilter("population_id", "==", population_id))
        return sorted((doc.to_dict() for doc in query.stream()), key=lambda p: p["persona_id"])

    def update_clusters(self, assignment: dict[str, dict]) -> None:
        """Set cluster_id and is_cluster_representative on existing personas."""
        items = list(assignment.items())
        collection = self._db.collection("personas")
        for start in range(0, len(items), WRITE_BATCH_LIMIT):
            batch = self._db.batch()
            for persona_id, fields in items[start:start + WRITE_BATCH_LIMIT]:
                batch.update(collection.document(persona_id), fields)
            batch.commit()

    def write_personas(self, personas: list[dict]) -> None:
        collection = self._db.collection("personas")
        for start in range(0, len(personas), WRITE_BATCH_LIMIT):
            batch = self._db.batch()
            for persona in personas[start:start + WRITE_BATCH_LIMIT]:
                batch.set(collection.document(persona["persona_id"]), persona)
            batch.commit()
