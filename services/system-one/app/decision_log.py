"""Decision log in BigQuery `shadow_city.decisions` (CONTRACT.md §6, Layer 4).

One row per decision with its full evidence: inputs, option probabilities, chosen option,
model, cache status, token usage and cost. A failed write is logged and never fails a decision.
"""

import json
import logging
from datetime import datetime, timezone

from app.costs import Usage
from app.models import DecisionRequestItem, DecisionResponseItem

logger = logging.getLogger("system-one")


def decision_row(
    request: DecisionRequestItem, response: DecisionResponseItem, usage: Usage | None, cache: str,
    logged_at: datetime | None = None,
) -> dict:
    return {
        "logged_at": (logged_at or datetime.now(timezone.utc)).isoformat(),
        "decision_id": response.decision_id,
        "request_id": request.request_id,
        "scenario_id": request.scenario_id,
        "tick": request.tick,
        "persona_id": request.persona_id,
        "cluster_id": request.cluster_id,
        "question_type": request.question_type.value,
        "options": [o.value for o in request.options],
        "chosen": response.chosen.value,
        "probabilities": json.dumps({o.value: p for o, p in response.probabilities.items()}),
        "reason_short": response.reason_short,
        "decided_by": response.decided_by.value,
        "model_version": response.model_version,
        "latency_ms": response.latency_ms,
        "cache": cache,
        "prompt_tokens": usage.prompt_tokens if usage else None,
        "output_tokens": usage.output_tokens if usage else None,
        "thoughts_tokens": usage.thoughts_tokens if usage else None,
        "cost_usd": usage.cost_usd if usage else None,
        "request": json.dumps(request.model_dump(mode="json")),
        "response": json.dumps(response.model_dump(mode="json")),
    }


class BigQueryDecisionLog:
    def __init__(self, bigquery_client, table: str):
        self._client = bigquery_client
        self._table = table  # "project.dataset.decisions"

    def write(self, rows: list[dict]) -> None:
        try:
            errors = self._client.insert_rows_json(self._table, rows)
            if errors:
                logger.error("BigQuery rejected %d decision rows: %s", len(errors), str(errors)[:500])
        except Exception:
            logger.exception("Writing %d decision rows to BigQuery failed", len(rows))
