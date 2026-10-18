#!/usr/bin/env python3
"""How much accuracy does sharing one decision per cluster cost? (Layer 6)

Uses a scenario in which every resident was decided individually (e.g. the demo baseline): for
each cluster, compares each member's own Gemini favourite with the representative's favourite.
Random clusters of the same sizes are the control.

Usage (from services/orchestrator):
  bq query --format=json ... > decisions.json   # persona_id, probabilities, options per resident
  .venv/bin/python tools/eval_clustering.py --population pop_s42_n1000 --decisions decisions.json
"""

import argparse
import json
import random
import statistics

from google.cloud import firestore

from app.clustering import cluster_personas, cluster_stats
from app.store import FirestoreStore


def favourite(probs: dict) -> str:
    return max(sorted(probs), key=lambda k: probs[k])


def shared_agreement(clusters: dict[str, list[str]], reps: dict[str, str], fav: dict[str, str]) -> float:
    """Share of non-representative members whose own favourite equals their representative's."""
    hits = total = 0
    for cluster_id, members in clusters.items():
        rep = reps[cluster_id]
        for pid in members:
            if pid != rep and pid in fav and rep in fav:
                total += 1
                hits += fav[pid] == fav[rep]
    return round(hits / total, 3) if total else 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--population", required=True)
    parser.add_argument("--decisions", required=True)
    parser.add_argument("--target-size", type=int, default=15)
    args = parser.parse_args()

    rows = json.load(open(args.decisions))
    fav = {r["persona_id"]: favourite(json.loads(r["probabilities"]) if isinstance(r["probabilities"], str)
                                      else r["probabilities"]) for r in rows}
    store = FirestoreStore(firestore.Client(project="ebc-cloud-dev-03", database="shadow-city"))
    personas = store.personas_for(args.population)
    assignment = cluster_personas(personas, args.population, args.target_size)

    clusters: dict[str, list[str]] = {}
    reps: dict[str, str] = {}
    for pid, a in assignment.items():
        clusters.setdefault(a["cluster_id"], []).append(pid)
        if a["is_cluster_representative"]:
            reps[a["cluster_id"]] = pid

    # Control: the same cluster sizes, members drawn at random (seeded).
    rng = random.Random(42)
    ids = sorted(assignment)
    rng.shuffle(ids)
    random_clusters, random_reps, start = {}, {}, 0
    for cluster_id, members in sorted(clusters.items()):
        chosen = ids[start:start + len(members)]
        start += len(members)
        random_clusters[cluster_id], random_reps[cluster_id] = chosen, chosen[0]

    print(json.dumps({
        **cluster_stats(assignment),
        "target_size": args.target_size,
        "shared_decision_agreement": shared_agreement(clusters, reps, fav),
        "random_clusters_agreement": shared_agreement(random_clusters, random_reps, fav),
        "favourite_distribution": dict(statistics.multimode(fav.values()) and
                                       sorted(((m, list(fav.values()).count(m)) for m in set(fav.values())),
                                              key=lambda x: -x[1])),
    }, indent=1))


if __name__ == "__main__":
    main()
