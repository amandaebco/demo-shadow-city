"""Decision evidence log (AGENTS.md: every decision is logged with its evidence).

Writes one JSON line per decision to stdout, which Cloud Logging ingests as a
structured entry. TODO(Layer 4): also write to BigQuery shadow_city.decisions.
"""

import json
import sys

from app.costs import Usage
from app.models import DecisionRequestItem, DecisionResponseItem


def log_decision(request: DecisionRequestItem, response: DecisionResponseItem, usage: Usage | None = None) -> None:
    entry = {
        "severity": "INFO",
        "message": f"decision {response.decision_id} by {response.decided_by.value}",
        "event": "decision",
        "request": request.model_dump(mode="json"),
        "response": response.model_dump(mode="json"),
        # Token usage and cost of this decision (None for the rule mock).
        "usage": usage.as_dict() if usage else None,
    }
    print(json.dumps(entry), file=sys.stdout, flush=True)
