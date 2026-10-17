"""Deterministic simulation engine for Layer 0 (placeholder) and Layer 1 (straight-line MVP)."""

from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Protocol

from sim_worker.config import (
    BASE_HOUR,
    MINUTES_PER_TICK,
    START_TICK,
    TOTAL_TICKS,
)
from sim_worker.physics import ZoneIndex, compute_options_detail


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


def simulate_scenario_layer1(
    scenario: dict[str, Any],
    personas: list[dict[str, Any]],
    zones: ZoneIndex,
    decision_provider: DecisionProvider,
    total_ticks: int = TOTAL_TICKS,
) -> SimulationResult:
    """Run Layer 1 straight-line simulation with System One mode_choice decisions."""
    scenario_id = scenario["scenario_id"]
    policies = scenario.get("policies") or []
    events = scenario.get("events") or []

    # Sort personas deterministically by persona_id
    sorted_personas = sorted(personas, key=lambda p: p["persona_id"])

    # 1. Build mode_choice decision requests for each persona at their usual_departure_tick
    request_items: list[dict[str, Any]] = []
    persona_options_map: dict[str, dict[str, dict[str, Any]]] = {}

    for p in sorted_personas:
        pid = p["persona_id"]
        dep_tick = max(0, min(total_ticks - 2, int(p.get("usual_departure_tick", 24))))
        options, options_detail, active_pol_str, active_ev_str = compute_options_detail(
            persona=p,
            tick=dep_tick,
            policies=policies,
            events=events,
            zones=zones,
        )
        persona_options_map[pid] = options_detail

        req_id = f"q_{scenario_id}_{pid}_t{dep_tick:04d}"
        request_items.append(
            {
                "request_id": req_id,
                "scenario_id": scenario_id,
                "tick": dep_tick,
                "persona_id": pid,
                "cluster_id": p.get("cluster_id", pid),
                "question_type": "mode_choice",
                "options": options,
                "context": {
                    "persona_summary": p.get("profile_summary", ""),
                    "cost_sensitivity": float(p.get("cost_sensitivity", 0.5)),
                    "time_sensitivity": float(p.get("time_sensitivity", 0.5)),
                    "memory": list(p.get("memory") or [])[-5:],
                    "options_detail": options_detail,
                    "active_policies": active_pol_str,
                    "active_events": active_ev_str,
                },
            }
        )

    # 2. Batch-call System One for all personas
    responses = decision_provider.decide_batch(request_items)
    response_by_req_id = {r["request_id"]: r for r in responses}

    # 3. Precompute each persona's commute schedule and metrics
    persona_plans: list[dict[str, Any]] = []
    for p, req in zip(sorted_personas, request_items):
        pid = p["persona_id"]
        resp = response_by_req_id.get(req["request_id"], {})
        chosen_mode = resp.get("chosen")
        options_detail = persona_options_map[pid]
        if not chosen_mode or chosen_mode not in options_detail:
            chosen_mode = p.get("usual_mode")
            if chosen_mode not in options_detail:
                chosen_mode = req["options"][0]

        chosen_detail = options_detail[chosen_mode]
        est_min = int(chosen_detail["est_minutes"])
        cost_idr = int(chosen_detail["cost_idr"])
        flooded = bool(chosen_detail["flooded_on_route"])

        dep_tick = int(req["tick"])
        travel_ticks = max(1, math.ceil(est_min / MINUTES_PER_TICK))
        arr_tick = dep_tick + travel_ticks

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
                "home_lat": float(p["home"]["lat"]),
                "home_lng": float(p["home"]["lng"]),
                "work_lat": float(p["work"]["lat"]),
                "work_lng": float(p["work"]["lng"]),
            }
        )

    # 4. Step through ticks 0..total_ticks-1 and interpolate straight-line positions
    tick_states: list[TickState] = []
    for tick in range(START_TICK, total_ticks):
        pids: list[str] = []
        lats: list[float] = []
        lngs: list[float] = []
        modes: list[str] = []
        statuses: list[str] = []

        for plan in persona_plans:
            pids.append(plan["persona_id"])
            modes.append(plan["chosen_mode"])
            dep_tick = plan["dep_tick"]
            arr_tick = plan["arr_tick"]

            if tick < dep_tick:
                lats.append(round(plan["home_lat"], 5))
                lngs.append(round(plan["home_lng"], 5))
                statuses.append("at_home")
            elif tick < arr_tick:
                frac = (tick - dep_tick + 1) / (plan["travel_ticks"] + 1)
                lat = plan["home_lat"] + (plan["work_lat"] - plan["home_lat"]) * frac
                lng = plan["home_lng"] + (plan["work_lng"] - plan["home_lng"]) * frac
                lats.append(round(lat, 5))
                lngs.append(round(lng, 5))
                if plan["flooded"] and 0.35 <= frac <= 0.65:
                    statuses.append("stuck")
                else:
                    statuses.append("traveling")
            else:
                lats.append(round(plan["work_lat"], 5))
                lngs.append(round(plan["work_lng"], 5))
                statuses.append("at_work")

        tick_states.append(
            TickState(
                scenario_id=scenario_id,
                tick=tick,
                tick_id=format_tick_id(tick),
                simulated_time=tick_to_local_time(tick),
                persona_ids=pids,
                lat=lats,
                lng=lngs,
                mode=modes,
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
    )


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
        kel = p.get("home", {}).get("kelurahan", "Unknown")
        inc = p.get("income_band", "middle")
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
