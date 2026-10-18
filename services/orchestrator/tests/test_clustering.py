from app.clustering import cluster_personas, cluster_stats


def persona(i, mode="motorcycle", vehicles=("motorcycle",), income="low", lat=-6.2, lng=106.8, cost=0.5):
    return {"persona_id": f"p_x_{i:05d}", "usual_mode": mode, "vehicles": list(vehicles), "income_band": income,
            "home": {"lat": lat + (i % 7) * 0.001, "lng": lng}, "work": {"lat": -6.2, "lng": 106.83},
            "cost_sensitivity": cost, "time_sensitivity": 0.5, "usual_departure_tick": 24}


def test_every_persona_gets_exactly_one_cluster_and_one_representative_each():
    people = [persona(i) for i in range(40)] + [persona(100 + i, mode="krl", vehicles=()) for i in range(20)]
    result = cluster_personas(people, "pop_x")
    assert set(result) == {p["persona_id"] for p in people}
    clusters: dict[str, list] = {}
    for pid, a in result.items():
        clusters.setdefault(a["cluster_id"], []).append(a["is_cluster_representative"])
    assert all(reps.count(True) == 1 for reps in clusters.values())


def test_clusters_never_mix_modes_vehicles_or_income():
    people = [persona(i) for i in range(30)] + [persona(50 + i, income="high") for i in range(30)] + \
             [persona(90 + i, mode="car", vehicles=("car",)) for i in range(30)]
    result = cluster_personas(people, "pop_x")
    by_id = {p["persona_id"]: p for p in people}
    members: dict[str, set] = {}
    for pid, a in result.items():
        p = by_id[pid]
        members.setdefault(a["cluster_id"], set()).add((p["usual_mode"], tuple(p["vehicles"]), p["income_band"]))
    assert all(len(keys) == 1 for keys in members.values())


def test_target_size_and_geography():
    north = [persona(i, lat=-6.11) for i in range(30)]
    south = [persona(100 + i, lat=-6.32) for i in range(30)]
    result = cluster_personas(north + south, "pop_x", target_size=30)
    north_clusters = {result[p["persona_id"]]["cluster_id"] for p in north}
    south_clusters = {result[p["persona_id"]]["cluster_id"] for p in south}
    assert north_clusters.isdisjoint(south_clusters)
    stats = cluster_stats(result)
    assert stats["clusters"] == 2 and stats["decisions_saved_share"] == round(1 - 2 / 60, 3)


def test_deterministic_and_order_independent():
    people = [persona(i, cost=(i % 10) / 10) for i in range(80)]
    assert cluster_personas(people, "pop_x") == cluster_personas(list(reversed(people)), "pop_x")


def test_cluster_ids_use_population_prefix():
    result = cluster_personas([persona(1)], "pop_s42_n1000")
    assert result["p_x_00001"] == {"cluster_id": "c_s42_n1000_00000", "is_cluster_representative": True}
