"""Firestore and Pub/Sub runner for Shadow City Layer 1 simulation worker."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from google.api_core.exceptions import AlreadyExists, NotFound
from google.cloud import firestore, pubsub_v1

from sim_worker.config import TOTAL_TICKS, WorkerConfig
from sim_worker.engine import DecisionProvider, SimulationResult, simulate_scenario_layer1
from sim_worker.physics import ZoneIndex
from sim_worker.system_one import SystemOneClient

logger = logging.getLogger("sim_worker.runner")

TOPIC_SCENARIO_START = "scenario-start"
TOPIC_SCENARIO_COMPLETED = "scenario-completed"
TOPIC_SCENARIO_FAILED = "scenario-failed"

TICK_WRITE_BATCH_SIZE = 50


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format (e.g. 2026-10-17T10:50:00Z)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SimulationRunner:
    """Coordinates reading scenarios/personas from Firestore, running the engine, and writing results."""

    def __init__(
        self,
        config: WorkerConfig,
        db: firestore.Client | None = None,
        publisher: pubsub_v1.PublisherClient | None = None,
        decision_provider: DecisionProvider | None = None,
    ) -> None:
        self.config = config
        self.db = db or firestore.Client(
            project=config.gcp_project_id,
            database=config.firestore_database,
        )
        self.publisher = publisher or pubsub_v1.PublisherClient()
        self.decision_provider = decision_provider or SystemOneClient(
            base_url=config.system_one_url
        )
        self.zones = ZoneIndex.from_file(config.zones_geojson_path)

    def _publish_event(self, topic_name: str, payload: dict[str, Any]) -> None:
        topic_path = self.publisher.topic_path(self.config.gcp_project_id, topic_name)
        data = json.dumps(payload).encode("utf-8")
        try:
            future = self.publisher.publish(topic_path, data=data)
            msg_id = future.result(timeout=15)
            logger.info("Published to %s (message_id=%s): %s", topic_name, msg_id, payload)
        except Exception as exc:
            logger.warning("Failed to publish to %s: %s", topic_name, exc)

    def load_scenario(self, scenario_id: str) -> dict[str, Any]:
        doc_ref = self.db.collection("scenarios").document(scenario_id)
        snap = doc_ref.get()
        if not snap.exists:
            raise ValueError(f"Scenario {scenario_id!r} not found in Firestore ({self.config.firestore_database})")
        data = snap.to_dict() or {}
        data.setdefault("scenario_id", scenario_id)
        return data

    def load_personas(self, scenario: dict[str, Any]) -> list[dict[str, Any]]:
        population_id = scenario.get("population_id")
        if not population_id:
            seed = scenario.get("seed", 42)
            pop_size = scenario.get("population_size", 50)
            population_id = f"pop_s{seed}_n{pop_size}"

        logger.info("Loading personas for population_id=%s...", population_id)
        query = self.db.collection("personas").where(
            filter=firestore.FieldFilter("population_id", "==", population_id)
        )
        personas: list[dict[str, Any]] = []
        for doc in query.stream():
            pdata = doc.to_dict() or {}
            pdata.setdefault("persona_id", doc.id)
            personas.append(pdata)

        if not personas:
            raise RuntimeError(
                f"No personas found in Firestore ({self.config.firestore_database}) "
                f"for population_id={population_id!r}"
            )
        personas.sort(key=lambda p: p["persona_id"])
        logger.info("Loaded %d personas for population_id=%s", len(personas), population_id)
        return personas

    def run_scenario(self, scenario_id: str) -> SimulationResult:
        """Execute a scenario end-to-end and persist ticks, metrics, and status."""
        scenario_ref = self.db.collection("scenarios").document(scenario_id)
        try:
            scenario = self.load_scenario(scenario_id)
            total_ticks = int(
                (scenario.get("progress") or {}).get("total_ticks") or TOTAL_TICKS
            )

            # 1. Mark scenario as running
            scenario_ref.update(
                {
                    "status": "running",
                    "progress": {"current_tick": 0, "total_ticks": total_ticks},
                    "updated_at": utc_now_iso(),
                }
            )

            # 2. Load personas and run simulation
            personas = self.load_personas(scenario)
            result = simulate_scenario_layer1(
                scenario=scenario,
                personas=personas,
                zones=self.zones,
                decision_provider=self.decision_provider,
                total_ticks=total_ticks,
            )

            # 3. Write tick documents in batches and update progress
            ticks_col = scenario_ref.collection("ticks")
            tick_states = result.tick_states
            for start in range(0, len(tick_states), TICK_WRITE_BATCH_SIZE):
                chunk = tick_states[start : start + TICK_WRITE_BATCH_SIZE]
                batch = self.db.batch()
                for ts in chunk:
                    batch.set(ticks_col.document(ts.tick_id), ts.to_firestore_dict())
                last_tick_in_chunk = chunk[-1].tick
                batch.update(
                    scenario_ref,
                    {
                        "progress": {
                            "current_tick": last_tick_in_chunk,
                            "total_ticks": total_ticks,
                        },
                        "updated_at": utc_now_iso(),
                    },
                )
                batch.commit()
                logger.info(
                    "Committed ticks %s..%s for scenario %s",
                    chunk[0].tick_id,
                    chunk[-1].tick_id,
                    scenario_id,
                )

            # 4. Write scenarios/{id}/metrics/summary
            metrics_ref = scenario_ref.collection("metrics").document("summary")
            metrics_ref.set(result.metrics_summary)
            logger.info("Wrote scenarios/%s/metrics/summary", scenario_id)

            # 5. Mark scenario completed and publish scenario-completed
            scenario_ref.update(
                {
                    "status": "completed",
                    "progress": {
                        "current_tick": total_ticks - 1,
                        "total_ticks": total_ticks,
                    },
                    "updated_at": utc_now_iso(),
                }
            )
            self._publish_event(
                TOPIC_SCENARIO_COMPLETED,
                {"scenario_id": scenario_id, "status": "completed"},
            )
            return result

        except Exception as exc:
            logger.exception("Scenario %s failed: %s", scenario_id, exc)
            try:
                scenario_ref.update(
                    {
                        "status": "failed",
                        "updated_at": utc_now_iso(),
                    }
                )
            except Exception:
                pass
            self._publish_event(
                TOPIC_SCENARIO_FAILED,
                {
                    "scenario_id": scenario_id,
                    "stage": "simulation",
                    "error": {"code": "INTERNAL", "message": str(exc)},
                },
            )
            raise


def ensure_pubsub_subscription(config: WorkerConfig) -> str:
    """Ensure the pull subscription on topic scenario-start exists in ebc-cloud-dev-03."""
    subscriber = pubsub_v1.SubscriberClient()
    publisher = pubsub_v1.PublisherClient()
    sub_path = subscriber.subscription_path(
        config.gcp_project_id, config.pubsub_subscription
    )
    topic_path = publisher.topic_path(config.gcp_project_id, TOPIC_SCENARIO_START)
    try:
        subscriber.get_subscription(request={"subscription": sub_path})
        logger.info("Using existing Pub/Sub subscription %s", sub_path)
    except NotFound:
        logger.info("Creating Pub/Sub subscription %s on %s...", sub_path, topic_path)
        try:
            subscriber.create_subscription(
                request={
                    "name": sub_path,
                    "topic": topic_path,
                    "ack_deadline_seconds": 600,
                }
            )
        except AlreadyExists:
            pass
    return sub_path


def listen_for_scenarios(
    runner: SimulationRunner,
    max_messages: int | None = None,
    timeout_sec: float = 30.0,
) -> int:
    """Pull messages from scenario-start subscription and run each scenario."""
    sub_path = ensure_pubsub_subscription(runner.config)
    subscriber = pubsub_v1.SubscriberClient()
    processed = 0

    logger.info("Listening for scenario-start messages on %s...", sub_path)
    while True:
        response = subscriber.pull(
            request={"subscription": sub_path, "max_messages": 1},
            timeout=timeout_sec,
        )
        if not response.received_messages:
            if max_messages is not None:
                break
            continue

        for received in response.received_messages:
            ack_id = received.ack_id
            raw_data = received.message.data.decode("utf-8")
            logger.info("Received scenario-start message: %s", raw_data)
            try:
                payload = json.loads(raw_data)
                scenario_id = payload["scenario_id"]
                subscriber.acknowledge(
                    request={"subscription": sub_path, "ack_ids": [ack_id]}
                )
                runner.run_scenario(scenario_id)
                processed += 1
            except Exception as exc:
                logger.error("Error processing Pub/Sub message %s: %s", raw_data, exc)
                subscriber.acknowledge(
                    request={"subscription": sub_path, "ack_ids": [ack_id]}
                )

            if max_messages is not None and processed >= max_messages:
                return processed

    return processed

