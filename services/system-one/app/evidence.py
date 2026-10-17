"""Decision evidence log (AGENTS.md: every decision is logged with its evidence).

Writes one JSON line per decision to stdout, which Cloud Logging ingests as a
structured entry. TODO(Layer 4): also write to BigQuery shadow_city.decisions.
"""

import json
import sys

from app.models import DecisionRequestItem, DecisionResponseItem


def log_decision(request: DecisionRequestItem, response: DecisionResponseItem) -> None:
    entry = {
        "severity": "INFO",
        "message": f"decision {response.decision_id} by {response.decided_by.value}",
        "event": "decision",
        "request": request.model_dump(mode="json"),
        "response": response.model_dump(mode="json"),
    }
    print(json.dumps(entry), file=sys.stdout, flush=True)
