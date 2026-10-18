"""Persona clustering (Layer 6, REFERENCE.md §6.5).

Residents with similar profiles share one decision: the engine asks System One once per
cluster, using the representative's context, and each member samples its own choice from
those probabilities (CONTRACT.md §4.6).

Deterministic, no randomness:
1. Group by what decides a resident's private options and taste: usual mode, vehicles owned,
   income band. Members of a cluster therefore never differ in which private vehicles they have.
2. Inside each group, k-means on home and work coordinates, cost and time sensitivity, and
   departure time (all scaled to comparable ranges), with k = ceil(group size / target size).
   Initial centroids are evenly spaced members in persona_id order.
3. The representative is the member closest to its cluster's centroid (ties: lowest persona_id).
"""

import math

TARGET_SIZE = 15
ITERATIONS = 25
# Feature scales: ~0.1 degree (≈11 km) of latitude/longitude counts like a full sensitivity range.
COORD_SCALE = 10.0
TICK_SCALE = 1 / 48  # four hours of departure time ≈ one unit


def features(persona: dict) -> tuple[float, ...]:
    home, work = persona.get("home") or {}, persona.get("work") or {}
    return (
        home.get("lat", 0.0) * COORD_SCALE, home.get("lng", 0.0) * COORD_SCALE,
        work.get("lat", 0.0) * COORD_SCALE, work.get("lng", 0.0) * COORD_SCALE,
        float(persona.get("cost_sensitivity", 0.5)), float(persona.get("time_sensitivity", 0.5)),
        float(persona.get("usual_departure_tick", 24)) * TICK_SCALE,
    )


def group_key(persona: dict) -> tuple:
    return (persona.get("usual_mode"), tuple(sorted(persona.get("vehicles") or [])), persona.get("income_band"))


def _distance(a: tuple, b: tuple) -> float:
    return math.dist(a, b)


def _kmeans(points: list[tuple], k: int) -> list[int]:
    """Assignment of each point to one of k clusters; deterministic."""
    step = len(points) / k
    centroids = [points[int(i * step)] for i in range(k)]
    assignment = [0] * len(points)
    for _ in range(ITERATIONS):
        changed = False
        for i, p in enumerate(points):
            best = min(range(k), key=lambda c: (_distance(p, centroids[c]), c))
            if best != assignment[i]:
                assignment[i], changed = best, True
        for c in range(k):
            members = [points[i] for i in range(len(points)) if assignment[i] == c]
            if members:
                centroids[c] = tuple(sum(dim) / len(members) for dim in zip(*members))
        if not changed:
            break
    return assignment


def cluster_personas(personas: list[dict], population_id: str, target_size: int = TARGET_SIZE) -> dict[str, dict]:
    """persona_id -> {"cluster_id", "is_cluster_representative"} for every persona."""
    groups: dict[tuple, list[dict]] = {}
    for persona in sorted(personas, key=lambda p: p["persona_id"]):
        groups.setdefault(group_key(persona), []).append(persona)

    result: dict[str, dict] = {}
    index = 0
    prefix = population_id.removeprefix("pop_")
    for key in sorted(groups, key=repr):
        members = groups[key]
        points = [features(p) for p in members]
        k = max(1, math.ceil(len(members) / target_size))
        assignment = _kmeans(points, k)
        for c in range(k):
            in_cluster = [i for i in range(len(members)) if assignment[i] == c]
            if not in_cluster:
                continue
            centroid = tuple(sum(dim) / len(in_cluster) for dim in zip(*(points[i] for i in in_cluster)))
            rep = min(in_cluster, key=lambda i: (_distance(points[i], centroid), members[i]["persona_id"]))
            cluster_id = f"c_{prefix}_{index:05d}"
            index += 1
            for i in in_cluster:
                result[members[i]["persona_id"]] = {"cluster_id": cluster_id, "is_cluster_representative": i == rep}
    return result


def cluster_stats(assignment: dict[str, dict]) -> dict:
    sizes: dict[str, int] = {}
    for a in assignment.values():
        sizes[a["cluster_id"]] = sizes.get(a["cluster_id"], 0) + 1
    values = sorted(sizes.values())
    return {
        "residents": len(assignment),
        "clusters": len(values),
        "decisions_saved_share": round(1 - len(values) / max(1, len(assignment)), 3),
        "median_cluster_size": values[len(values) // 2] if values else 0,
        "singleton_clusters": sum(1 for v in values if v == 1),
        "largest_cluster": values[-1] if values else 0,
    }
