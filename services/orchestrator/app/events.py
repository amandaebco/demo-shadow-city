"""Pub/Sub publishing (CONTRACT.md §6)."""

import json

from google.cloud import pubsub_v1


class PubSubPublisher:
    def __init__(self, project_id: str, topic_start: str, topic_failed: str):
        self._client = pubsub_v1.PublisherClient()
        self._start = self._client.topic_path(project_id, topic_start)
        self._failed = self._client.topic_path(project_id, topic_failed)

    def _publish(self, topic: str, message: dict) -> None:
        self._client.publish(topic, json.dumps(message).encode("utf-8")).result(timeout=30)

    def scenario_start(self, scenario_id: str, seed: int) -> None:
        self._publish(self._start, {"scenario_id": scenario_id, "seed": seed})

    def scenario_failed(self, scenario_id: str, stage: str, error: dict) -> None:
        self._publish(self._failed, {"scenario_id": scenario_id, "stage": stage, "error": error})
