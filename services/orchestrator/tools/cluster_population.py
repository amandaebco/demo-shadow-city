#!/usr/bin/env python3
"""Assign Layer 6 clusters to an existing population (new populations get them automatically).

Only cluster_id and is_cluster_representative change; decisions, ticks and metrics are untouched,
and the decision cache key does not include cluster_id.

Usage (from services/orchestrator):
  PYTHONPATH=. .venv/bin/python tools/cluster_population.py pop_s42_n1000 [--dry-run]
"""

import argparse
import json

from google.cloud import firestore

from app.clustering import cluster_personas, cluster_stats
from app.store import FirestoreStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("population_id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    store = FirestoreStore(firestore.Client(project="ebc-cloud-dev-03", database="shadow-city"))
    personas = store.personas_for(args.population_id)
    assignment = cluster_personas(personas, args.population_id)
    print(json.dumps(cluster_stats(assignment)))
    if not args.dry_run:
        store.update_clusters(assignment)
        print(f"updated {len(assignment)} personas")


if __name__ == "__main__":
    main()
