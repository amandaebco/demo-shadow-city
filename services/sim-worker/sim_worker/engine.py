"""Deterministic simulation engine for Layer 0, Layer 1, and Layer 2 (OSM road graph & station gating)."""

from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Protocol

from sim_worker.config import (
    BASE_HOUR,
    MINUTES_PER_TICK,
    START_TICK,
    TOTAL_TICKS,
)
from sim_worker.physics import ZoneIndex, compute_options_detail
from sim_worker.road_graph import JakartaNetwork, RoutePlan


class DecisionProvider(Protocol):
    """Protocol implemented by SystemOneClient (and test doubles)."""

    def decide_batch(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]: ...


def format_tick_id(tick: int) -> str:
    """Format a tick number as a 4-digit zero-padded string per CONTRACT.md section 5."""
    if tick < 0 or tick >= TOTAL_TICKS:
        raise ValueError(f"tick must be between {START_TICK} and {TOTAL_TICKS - 1}, got {tick}")
    return f"{tick:04d}"


def tick_to_local_time(tick: int) -> str:
    """Convert a tick index (0 = 05:00) into HH:MM local time string."""
    total_minutes = BASE_HOUR * 60 + tick * MINUTES_PER_TICK
    hours = (total_minutes // 60) % 24
    minutes = total_minutes % 60
    return f"{hours:02d}:{minutes:02d}"


def make_tick_rng(seed: int, tick: int, salt: str = "") -> random.Random:
    """Create a deterministic RNG derived from scenario seed, tick, and optional salt."""
    payload = f"{seed}:{tick}:{salt}".encode("utf-8")
    derived_seed = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
    return random.Random(derived_seed)


# Frozen demo scenario IDs whose numbers are in the submission deck and video.
# Clustering is left off for these scenarios and they must never be overwritten.
FROZEN_DEMO_SCENARIO_IDS: frozenset[str] = frozenset(
    {
        "s_baseline_weekday_ea7247",
        "s_central_parking_100_af902a",
        "s_central_parking_100_with_north_jakarta_t_78f06b",
    }
)


def persona_hash(persona_id: str) -> int:
    """Stable 32-bit hash of persona_id matching System One's sampling.persona_hash."""
    return int(hashlib.sha256(persona_id.encode("utf-8")).hexdigest()[:8], 16)


def make_decision_rng(seed: int, tick: int, persona_id: str) -> random.Random:
    """Deterministic RNG seeded with seed + tick + persona_id hash (CONTRACT.md §2.3, §4.6)."""
    return random.Random(int(seed) + int(tick) + persona_hash(persona_id))


def normalize_member_probabilities(
    raw_probs: dict[str, Any], member_options: list[str]
) -> dict[str, float]:
    """Restrict probabilities to the member's available options and rescale to sum to 1."""
    cleaned: dict[str, float] = {}
    for opt in member_options:
        val = raw_probs.get(opt, 0.0)
        try:
            fval = float(val)
        except (TypeError, ValueError):
            fval = 0.0
        cleaned[opt] = fval if math.isfinite(fval) and fval > 0.0 else 0.0
    total = sum(cleaned.values())
    if total <= 0.0:
        n = max(1, len(member_options))
        return {opt: 1.0 / n for opt in member_options}
    return {opt: cleaned[opt] / total for opt in member_options}


def sample_mode_choice(probabilities: dict[str, float], rng: random.Random) -> str:
    """Inverse-CDF sample over options in their listed order (CONTRACT.md §2.3, §4.6)."""
    r = rng.random()
    cumulative = 0.0
    last = next(iter(probabilities))
    for opt, prob in probabilities.items():
        cumulative += prob
        last = opt
        if r < cumulative:
            return opt
    return last


def flood_signature(options_detail: dict[str, dict[str, Any]]) -> tuple[str, ...]:
    """Return sorted tuple of options whose flooded_on_route is True (CONTRACT.md §4.6)."""
    return tuple(
        sorted(opt for opt, det in options_detail.items() if det.get("flooded_on_route"))
    )


@dataclass(frozen=True)
class TickState:
    """Per-tick state document shape matching CONTRACT.md section 2.4."""

    scenario_id: str
    tick: int
    tick_id: str
    simulated_time: str
    persona_ids: list[str]
    lat: list[float]
    lng: list[float]
    mode: list[str]
    status: list[str]

    def to_firestore_dict(self) -> dict[str, Any]:
        """Serialize to the exact Firestore schema defined in CONTRACT.md section 2.4."""
        return {
            "scenario_id": self.scenario_id,
            "tick": self.tick,
            "persona_ids": self.persona_ids,
            "lat": self.lat,
            "lng": self.lng,
            "mode": self.mode,
            "status": self.status,
        }


@dataclass(frozen=True)
class SimulationResult:
    """Complete output of a scenario simulation run."""

    scenario_id: str
    tick_states: list[TickState]
    metrics_summary: dict[str, Any]
    decisions: list[dict[str, Any]]
    scenario_memories: dict[str, list[str]] = field(default_factory=dict)
    persona_decisions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def run_placeholder_tick_loop(
    scenario_id: str,
    seed: int,
    total_ticks: int = TOTAL_TICKS,
) -> list[TickState]:
    """Run the Layer 0 deterministic placeholder tick loop from tick 0 to total_ticks - 1."""
    if total_ticks <= 0 or total_ticks > TOTAL_TICKS:
        raise ValueError(f"total_ticks must be in 1..{TOTAL_TICKS}, got {total_ticks}")

    states: list[TickState] = []
    for tick in range(START_TICK, total_ticks):
        _rng = make_tick_rng(seed=seed, tick=tick)
        states.append(
            TickState(
                scenario_id=scenario_id,
                tick=tick,
                tick_id=format_tick_id(tick),
                simulated_time=tick_to_local_time(tick),
                persona_ids=[],
                lat=[],
                lng=[],
                mode=[],
                status=[],
            )
        )
    return states


def simulate_scenario_layer2(
    scenario: dict[str, Any],
    personas: list[dict[str, Any]],
    zones: ZoneIndex,
    decision_provider: DecisionProvider,
    network: JakartaNetwork | None = None,
    total_ticks: int = TOTAL_TICKS,
    use_clustering: bool | None = None,
) -> SimulationResult:
    """Run Layer 2 / Layer 6 deterministic simulation over the Jakarta OSM road graph.

    Enforces:
    - Byte-for-byte reproducible System One decision requests (canonical option order,
      sorted active_policies/active_events, verbatim persona_summary, scenario-scoped memory).
    - Layer 6 cluster decision sharing (CONTRACT.md v1.7 §4.6) when use_clustering is True
      (or automatically when personas carry is_cluster_representative and scenario_id is not
      one of the three frozen demo scenarios).
    - Operational MRT/KRL station reachability gating and access/egress walking + wait times.
    - Multi-waypoint interpolation along the OSM road graph.
    - Scenario-scoped persona memory (never mutating personas/{id}.memory).
    """
    scenario_id = str(scenario["scenario_id"])
    seed = int(scenario.get("seed", 42))
    policies = list(scenario.get("policies") or [])
    events = list(scenario.get("events") or [])

    if network is None:
        network = JakartaNetwork.from_file()

    # Sort personas deterministically by persona_id
    sorted_personas = sorted(personas, key=lambda p: str(p["persona_id"]))

    if use_clustering is None:
        if scenario_id in FROZEN_DEMO_SCENARIO_IDS:
            effective_clustering = False
        else:
            effective_clustering = any(
                "is_cluster_representative" in p for p in sorted_personas
            )
    else:
        effective_clustering = bool(use_clustering)

    # Per-scenario memory state initialized from each persona's starting memory (max 5, newest last)
    # Per CONTRACT.md v1.4 sections 2.1, 4.3, 5: never write to personas/{id}.memory.
    scenario_memories: dict[str, list[str]] = {
        str(p["persona_id"]): [str(m) for m in list(p.get("memory") or [])[-5:]]
        for p in sorted_personas
    }

    # 1. Precompute each persona's route and available options_detail at their usual_departure_tick
    persona_dep_ticks: dict[str, int] = {}
    persona_options_list: dict[str, list[str]] = {}
    persona_options_map: dict[str, dict[str, dict[str, Any]]] = {}
    persona_routes_map: dict[str, RoutePlan] = {}
    persona_active_pol: dict[str, list[str]] = {}
    persona_active_ev: dict[str, list[str]] = {}

    for p in sorted_personas:
        pid = str(p["persona_id"])
        dep_tick = max(0, min(total_ticks - 2, int(p.get("usual_departure_tick", 24))))
        persona_dep_ticks[pid] = dep_tick

        home_lat = float(p["home"]["lat"])
        home_lng = float(p["home"]["lng"])
        work_lat = float(p["work"]["lat"])
        work_lng = float(p["work"]["lng"])

        route_plan = network.route(home_lat, home_lng, work_lat, work_lng)
        persona_routes_map[pid] = route_plan

        options, options_detail, active_pol_str, active_ev_str = compute_options_detail(
            persona=p,
            tick=dep_tick,
            policies=policies,
            events=events,
            zones=zones,
            network=network,
        )
        persona_options_list[pid] = options
        persona_options_map[pid] = options_detail
        persona_active_pol[pid] = active_pol_str
        persona_active_ev[pid] = active_ev_str

    def _build_request_item(p: dict[str, Any]) -> dict[str, Any]:
        pid = str(p["persona_id"])
        dep_tick = persona_dep_ticks[pid]
        req_id = f"q_{scenario_id}_{pid}_t{dep_tick:04d}"
        return {
            "request_id": req_id,
            "scenario_id": scenario_id,
            "tick": dep_tick,
            "persona_id": pid,
            "cluster_id": str(p.get("cluster_id", pid)),
            "question_type": "mode_choice",
            "options": persona_options_list[pid],
            "context": {
                "persona_summary": str(p.get("profile_summary", "")),
                "cost_sensitivity": float(p.get("cost_sensitivity", 0.5)),
                "time_sensitivity": float(p.get("time_sensitivity", 0.5)),
                "memory": list(scenario_memories[pid])[-5:],
                "options_detail": persona_options_map[pid],
                "active_policies": persona_active_pol[pid],
                "active_events": persona_active_ev[pid],
            },
        }

    # 2. Build /v1/decide requests: either 1 per group (Layer 6 clustering) or 1 per persona (Layers 1–4)
    request_items: list[dict[str, Any]] = []
    member_sender_map: dict[str, str] = {}
    sender_req_id_map: dict[str, str] = {}

    if effective_clustering:
        # CONTRACT.md v1.7 §4.6:
        # 1. Split each cluster's members by flood signature (set of options with flooded_on_route=True).
        # 2. Send one decision request per group, built from the cluster representative if in the group,
        #    otherwise the member with the lowest persona_id.
        groups: dict[tuple[str, tuple[str, ...]], list[dict[str, Any]]] = defaultdict(list)
        for p in sorted_personas:
            pid = str(p["persona_id"])
            cid = str(p.get("cluster_id", pid))
            fsig = flood_signature(persona_options_map[pid])
            groups[(cid, fsig)].append(p)

        group_requests: list[dict[str, Any]] = []
        for group_key in sorted(groups.keys()):
            members = groups[group_key]
            # members is already sorted by persona_id ascending
            reps = [m for m in members if bool(m.get("is_cluster_representative"))]
            sender = reps[0] if reps else members[0]
            sender_pid = str(sender["persona_id"])
            req_item = _build_request_item(sender)
            group_requests.append(req_item)
            sender_req_id_map[sender_pid] = req_item["request_id"]
            for m in members:
                member_sender_map[str(m["persona_id"])] = sender_pid

        # Order by (tick, persona_id) so batches are ordered per tick
        group_requests.sort(key=lambda r: (int(r["tick"]), str(r["persona_id"])))
        request_items = group_requests
    else:
        for p in sorted_personas:
            pid = str(p["persona_id"])
            req_item = _build_request_item(p)
            request_items.append(req_item)
            member_sender_map[pid] = pid
            sender_req_id_map[pid] = req_item["request_id"]

    # 3. Batch-call System One (<= 256 items per call)
    responses = decision_provider.decide_batch(request_items)
    response_by_req_id = {r["request_id"]: r for r in responses}

    # 4. Precompute each persona's commute schedule, road trajectory, decision record, and scenario memory
    persona_plans: list[dict[str, Any]] = []
    persona_decisions: dict[str, list[dict[str, Any]]] = {}
    for p in sorted_personas:
        pid = str(p["persona_id"])
        dep_tick = persona_dep_ticks[pid]
        options = persona_options_list[pid]
        options_detail = persona_options_map[pid]
        sender_pid = member_sender_map[pid]
        req_id = sender_req_id_map[sender_pid]
        resp = response_by_req_id.get(req_id, {})
        raw_probs = resp.get("probabilities") or {}

        if effective_clustering:
            # CONTRACT.md §4.6 step 3: each member samples its own chosen from the returned
            # probabilities, restricted to its own available options and rescaled to sum to 1,
            # with RNG seeded by seed + tick + persona_id hash of the member.
            member_probs = normalize_member_probabilities(raw_probs, options)
            if raw_probs:
                rng = make_decision_rng(seed=seed, tick=dep_tick, persona_id=pid)
                chosen_mode = sample_mode_choice(member_probs, rng)
            else:
                chosen_mode = resp.get("chosen")
            clean_probs = {str(k): round(float(v), 4) for k, v in member_probs.items()}
        else:
            chosen_mode = resp.get("chosen")
            clean_probs = {str(k): round(float(v), 4) for k, v in raw_probs.items()}

        if not chosen_mode or chosen_mode not in options_detail:
            chosen_mode = p.get("usual_mode")
            if chosen_mode not in options_detail:
                chosen_mode = options[0]

        chosen_detail = options_detail[chosen_mode]
        est_min = int(chosen_detail["est_minutes"])
        cost_idr = int(chosen_detail["cost_idr"])
        flooded = bool(chosen_detail["flooded_on_route"])

        travel_ticks = max(1, math.ceil(est_min / MINUTES_PER_TICK))
        arr_tick = dep_tick + travel_ticks

        # Record per-persona decision for evidence chain (CONTRACT.md v1.5 §4.5 & v1.7 §4.6)
        dec_record: dict[str, Any] = {
            "tick": dep_tick,
            "options_detail": options_detail,
            "probabilities": clean_probs,
            "chosen": str(chosen_mode),
            "reason_short": str(resp.get("reason_short") or ""),
            "decided_by": str(resp.get("decided_by") or "gemini-system-two"),
        }
        if effective_clustering:
            dec_record["shared_from"] = sender_pid
        persona_decisions[pid] = [dec_record]

        # Update per-scenario memory after decision/commute (capped at 5, newest last)
        mem_entry = (
            f"Tick {dep_tick:04d}: commuted via {chosen_mode} "
            f"({est_min} min, IDR {cost_idr}"
            f"{', flooded route' if flooded else ''})."
        )
        updated_mem = (scenario_memories[pid] + [mem_entry])[-5:]
        scenario_memories[pid] = updated_mem

        route_plan = persona_routes_map[pid]
        home_lat = round(float(p["home"]["lat"]), 5)
        home_lng = round(float(p["home"]["lng"]), 5)
        work_lat = round(float(p["work"]["lat"]), 5)
        work_lng = round(float(p["work"]["lng"]), 5)

        # Precompute traveling ticks (dep_tick <= tick < arr_tick) once per resident
        travel_steps: dict[int, tuple[float, float, str]] = {}
        end_travel_tick = min(total_ticks, arr_tick)
        denom = travel_ticks + 1
        for t in range(dep_tick, end_travel_tick):
            frac = (t - dep_tick + 1) / denom
            lat, lng = route_plan.interpolate(frac)
            st = "stuck" if (flooded and 0.35 <= frac <= 0.65) else "traveling"
            travel_steps[t] = (lat, lng, st)

        persona_plans.append(
            {
                "persona": p,
                "persona_id": pid,
                "chosen_mode": chosen_mode,
                "est_minutes": est_min,
                "cost_idr": cost_idr,
                "flooded": flooded,
                "dep_tick": dep_tick,
                "travel_ticks": travel_ticks,
                "arr_tick": arr_tick,
                "home_lat": home_lat,
                "home_lng": home_lng,
                "work_lat": work_lat,
                "work_lng": work_lng,
                "route_plan": route_plan,
                "travel_steps": travel_steps,
            }
        )

    # 5. Step through ticks 0..total_ticks-1 using precomputed travel steps
    shared_pids: list[str] = [plan["persona_id"] for plan in persona_plans]
    shared_modes: list[str] = [plan["chosen_mode"] for plan in persona_plans]
    tick_states: list[TickState] = []

    for tick in range(START_TICK, total_ticks):
        lats: list[float] = []
        lngs: list[float] = []
        statuses: list[str] = []

        for plan in persona_plans:
            dep_tick = plan["dep_tick"]
            if tick < dep_tick:
                lats.append(plan["home_lat"])
                lngs.append(plan["home_lng"])
                statuses.append("at_home")
            elif tick < plan["arr_tick"]:
                lat, lng, st = plan["travel_steps"][tick]
                lats.append(lat)
                lngs.append(lng)
                statuses.append(st)
            else:
                lats.append(plan["work_lat"])
                lngs.append(plan["work_lng"])
                statuses.append("at_work")

        tick_states.append(
            TickState(
                scenario_id=scenario_id,
                tick=tick,
                tick_id=format_tick_id(tick),
                simulated_time=tick_to_local_time(tick),
                persona_ids=list(shared_pids),
                lat=lats,
                lng=lngs,
                mode=list(shared_modes),
                status=statuses,
            )
        )

    # 5. Aggregate scenario metrics (CONTRACT.md section 2.5)
    metrics_summary = _compute_metrics_summary(scenario_id, persona_plans)

    return SimulationResult(
        scenario_id=scenario_id,
        tick_states=tick_states,
        metrics_summary=metrics_summary,
        decisions=responses,
        scenario_memories=scenario_memories,
        persona_decisions=persona_decisions,
    )


# Backward-compatible alias for Layer 1 callers and tests
simulate_scenario_layer1 = simulate_scenario_layer2


def _compute_mode_share(modes: list[str]) -> dict[str, float]:
    if not modes:
        return {}
    counts: dict[str, int] = defaultdict(int)
    for m in modes:
        counts[m] += 1
    total = len(modes)
    shares = {m: round(c / total, 4) for m, c in sorted(counts.items())}
    return shares


def _compute_metrics_summary(
    scenario_id: str, persona_plans: list[dict[str, Any]]
) -> dict[str, Any]:
    """Compute scenarios/{id}/metrics/summary per CONTRACT.md section 2.5."""
    by_kel: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_inc: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for plan in persona_plans:
        p = plan["persona"]
        kel = str(p.get("home", {}).get("kelurahan", "Unknown"))
        inc = str(p.get("income_band", "middle"))
        by_kel[kel].append(plan)
        by_inc[inc].append(plan)

    kelurahan_rows: list[dict[str, Any]] = []
    for kel in sorted(by_kel.keys()):
        plans = by_kel[kel]
        n = len(plans)
        avg_min = round(sum(x["est_minutes"] for x in plans) / n, 1)
        avg_cost = int(round(sum(x["cost_idr"] for x in plans) / n))
        stuck_cnt = sum(1 for x in plans if x["flooded"])
        kelurahan_rows.append(
            {
                "kelurahan": kel,
                "residents": n,
                "avg_travel_min": avg_min,
                "avg_cost_idr": avg_cost,
                "mode_share": _compute_mode_share([x["chosen_mode"] for x in plans]),
                "stuck_count": stuck_cnt,
                "cancelled_count": 0,
            }
        )

    income_order = ["low", "lower_middle", "middle", "upper_middle", "high"]
    income_rows: list[dict[str, Any]] = []
    for inc in income_order:
        plans = by_inc.get(inc)
        if not plans:
            continue
        n = len(plans)
        income_rows.append(
            {
                "income_band": inc,
                "avg_travel_min": round(sum(x["est_minutes"] for x in plans) / n, 1),
                "avg_cost_idr": int(round(sum(x["cost_idr"] for x in plans) / n)),
                "stuck_count": sum(1 for x in plans if x["flooded"]),
            }
        )

    total_n = max(1, len(persona_plans))
    citywide = {
        "avg_travel_min": round(
            sum(x["est_minutes"] for x in persona_plans) / total_n, 1
        ),
        "avg_cost_idr": int(
            round(sum(x["cost_idr"] for x in persona_plans) / total_n)
        ),
        "mode_share": _compute_mode_share([x["chosen_mode"] for x in persona_plans]),
        "stuck_count": sum(1 for x in persona_plans if x["flooded"]),
        "cancelled_count": 0,
    }

    return {
        "scenario_id": scenario_id,
        "by_kelurahan": kelurahan_rows,
        "by_income_band": income_rows,
        "citywide": citywide,
    }
