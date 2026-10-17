"""Deterministic physical calculations for Shadow City Layer 2 (OSM road graph & station gating).

All physical numbers (road distances, travel times, IDR costs, station reachability,
flood intersections) are computed deterministically here. LLMs never compute physical numbers.
Model assumptions are imported from `sim_worker.assumptions`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sim_worker.assumptions import (
    CANONICAL_MODES,
    CAR_FUEL_AND_TOLL_IDR_PER_KM,
    CAR_MINUTES_PER_KM,
    CAR_PARKING_CENTRAL_IDR,
    CAR_PARKING_EGRESS_MIN,
    CAR_PARKING_NON_CENTRAL_IDR,
    EVENING_PEAK_TICK_RANGE,
    FALLBACK_URBAN_DETOUR_FACTOR,
    FLOOD_DELAY_BRT_MIN_PER_CM,
    FLOOD_DELAY_ROAD_MIN_PER_CM,
    KRL_BASE_FARE_IDR,
    KRL_CATCHMENT_KM,
    KRL_DISTANCE_THRESHOLD_KM,
    KRL_INCREMENT_FARE_IDR,
    KRL_INCREMENT_STEP_KM,
    KRL_IN_VEHICLE_MINUTES_PER_KM,
    KRL_WAIT_MIN,
    MAX_WALK_COMMUTE_KM,
    MIN_TRIP_MINUTES,
    MORNING_PEAK_TICK_RANGE,
    MOTORCYCLE_FUEL_IDR_PER_KM,
    MOTORCYCLE_MINUTES_PER_KM,
    MOTORCYCLE_PARKING_CENTRAL_IDR,
    MOTORCYCLE_PARKING_EGRESS_MIN,
    MOTORCYCLE_PARKING_NON_CENTRAL_IDR,
    MRT_BASE_FARE_IDR,
    MRT_CATCHMENT_KM,
    MRT_INCREMENT_FARE_IDR,
    MRT_INCREMENT_STEP_KM,
    MRT_IN_VEHICLE_MINUTES_PER_KM,
    MRT_MAX_FARE_IDR,
    MRT_WAIT_MIN,
    OJOL_BASE_FARE_IDR,
    OJOL_IDR_PER_KM,
    OJOL_MIN_FARE_IDR,
    OJOL_MINUTES_PER_KM,
    OJOL_WAIT_MIN,
    PEAK_CONGESTION_MULTIPLIER,
    TRANSJAKARTA_BASE_FARE_IDR,
    TRANSJAKARTA_MINUTES_PER_KM,
    TRANSJAKARTA_WAIT_MIN,
    WALK_MINUTES_PER_KM,
)
from sim_worker.road_graph import JakartaNetwork, RailAccessPlan, haversine_km

# Re-export for backward compatibility with Layer 1 callers
URBAN_DETOUR_FACTOR = FALLBACK_URBAN_DETOUR_FACTOR


def _point_in_ring(lng: float, lat: float, ring: list[list[float]]) -> bool:
    """Ray-casting point-in-polygon ring check (coordinates in [lng, lat])."""
    inside = False
    n = len(ring)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        intersect = ((yi > lat) != (yj > lat)) and (
            lng < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
        )
        if intersect:
            inside = not inside
        j = i
    return inside


def _point_in_polygon_coords(lng: float, lat: float, polygon_coords: list[list[list[float]]]) -> bool:
    """Check if (lng, lat) is inside outer ring and not in any interior hole."""
    if not polygon_coords:
        return False
    if not _point_in_ring(lng, lat, polygon_coords[0]):
        return False
    for hole in polygon_coords[1:]:
        if _point_in_ring(lng, lat, hole):
            return False
    return True


class ZoneIndex:
    """Geospatial helper loaded from data/zones.geojson."""

    def __init__(self, features: list[dict[str, Any]]) -> None:
        self._by_id: dict[str, dict[str, Any]] = {}
        for feat in features:
            props = feat.get("properties") or {}
            zone_id = props.get("zone_id")
            if zone_id:
                self._by_id[zone_id] = feat

    @classmethod
    def from_file(cls, path: Path) -> ZoneIndex:
        if not path.exists():
            return cls([])
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data.get("features", []))

    def contains_point(self, zone_id: str, lat: float, lng: float) -> bool:
        feat = self._by_id.get(zone_id)
        if not feat:
            return False
        geom = feat.get("geometry") or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates") or []
        if gtype == "Polygon":
            return _point_in_polygon_coords(lng, lat, coords)
        if gtype == "MultiPolygon":
            return any(_point_in_polygon_coords(lng, lat, poly) for poly in coords)
        return False

    def contains_kelurahan_or_point(
        self, zone_id: str, lat: float, lng: float, kelurahan: str = ""
    ) -> bool:
        if self.contains_point(zone_id, lat, lng):
            return True
        feat = self._by_id.get(zone_id)
        if not feat or not kelurahan:
            return False
        kec_list = [k.lower() for k in (feat.get("properties", {}).get("kecamatan") or [])]
        return kelurahan.strip().lower() in kec_list

    def segment_intersects(
        self,
        zone_id: str,
        lat1: float,
        lng1: float,
        lat2: float,
        lng2: float,
        samples: int = 12,
    ) -> bool:
        for i in range(samples + 1):
            frac = i / max(1, samples)
            lat = lat1 + (lat2 - lat1) * frac
            lng = lng1 + (lng2 - lng1) * frac
            if self.contains_point(zone_id, lat, lng):
                return True
        return False

    def path_intersects(
        self,
        zone_id: str,
        waypoints: tuple[tuple[float, float], ...],
        samples_per_segment: int = 3,
    ) -> bool:
        """Check whether any waypoint or segment along a road path intersects zone_id."""
        if not waypoints:
            return False
        if len(waypoints) == 1:
            return self.contains_point(zone_id, waypoints[0][0], waypoints[0][1])
        for i in range(len(waypoints) - 1):
            lat1, lng1 = waypoints[i]
            lat2, lng2 = waypoints[i + 1]
            if self.segment_intersects(
                zone_id, lat1, lng1, lat2, lng2, samples=samples_per_segment
            ):
                return True
        return False


def format_active_policies(policies: list[dict[str, Any]]) -> list[str]:
    """Format active policies as deterministically sorted strings like 'parking_tariff:central:+100%'."""
    out: list[str] = []
    for p in policies:
        ptype = str(p.get("type", "policy"))
        zone = str(p.get("zone", "all"))
        ratio = float(p.get("change_ratio", 0.0))
        pct = int(round(ratio * 100))
        out.append(f"{ptype}:{zone}:{pct:+d}%")
    return sorted(out)


def get_active_events_at_tick(events: list[dict[str, Any]], tick: int) -> list[dict[str, Any]]:
    """Return events active at the given tick."""
    active: list[dict[str, Any]] = []
    for ev in events:
        start_tick = int(ev.get("start_tick", 0))
        end_tick = int(ev.get("end_tick", 203))
        if start_tick <= tick <= end_tick:
            active.append(ev)
    return active


def format_active_events(events: list[dict[str, Any]]) -> list[str]:
    """Format active events as deterministically sorted strings like 'flood:jakarta_utara'."""
    formatted = [
        f"{str(e.get('type', 'event'))}:{str(e.get('area_id', 'unknown'))}" for e in events
    ]
    return sorted(formatted)


def is_peak_tick(tick: int) -> bool:
    """Return True if tick falls within morning or evening peak periods."""
    m_start, m_end = MORNING_PEAK_TICK_RANGE
    e_start, e_end = EVENING_PEAK_TICK_RANGE
    return (m_start <= tick <= m_end) or (e_start <= tick <= e_end)


def available_modes_for_persona(
    persona: dict[str, Any],
    raw_dist_km: float,
    mrt_reachable: bool = False,
    krl_reachable: bool = False,
) -> list[str]:
    """Determine which transport modes are available to this persona in canonical order.

    Per Layer 2 rules:
    - MRT and KRL are offered only when operational stations are reachable from
      both home and work (or when the persona's stored usual_mode is that rail mode).
    - Returned options always follow CANONICAL_MODES order for request determinism.
    """
    vehicles = set(persona.get("vehicles") or [])
    usual = str(persona.get("usual_mode") or "motorcycle")

    allowed: set[str] = {"transjakarta", "ojol"}
    if "motorcycle" in vehicles or usual == "motorcycle":
        allowed.add("motorcycle")
    if "car" in vehicles or usual == "car":
        allowed.add("car")
    if krl_reachable or usual == "krl":
        allowed.add("krl")
    if mrt_reachable or usual == "mrt":
        allowed.add("mrt")
    if raw_dist_km <= MAX_WALK_COMMUTE_KM or usual == "walk":
        allowed.add("walk")

    options = [m for m in CANONICAL_MODES if m in allowed]
    if usual and usual not in options:
        options.append(usual)
    return options


def compute_options_detail(
    persona: dict[str, Any],
    tick: int,
    policies: list[dict[str, Any]],
    events: list[dict[str, Any]],
    zones: ZoneIndex,
    network: JakartaNetwork | None = None,
) -> tuple[list[str], dict[str, dict[str, Any]], list[str], list[str]]:
    """Compute options and options_detail for a persona at a given tick.

    Returns (options, options_detail, active_policies_str, active_events_str).
    All outputs are strictly deterministic for identical inputs.
    """
    home = persona["home"]
    work = persona["work"]
    home_lat, home_lng = float(home["lat"]), float(home["lng"])
    work_lat, work_lng = float(work["lat"]), float(work["lng"])

    raw_km = haversine_km(home_lat, home_lng, work_lat, work_lng)

    if network is not None and network.nodes_by_id:
        route_plan = network.route(home_lat, home_lng, work_lat, work_lng)
        dist_km = route_plan.total_km
        waypoints = route_plan.waypoints
    else:
        dist_km = max(0.8, round(raw_km * FALLBACK_URBAN_DETOUR_FACTOR, 4))
        waypoints = ((round(home_lat, 5), round(home_lng, 5)), (round(work_lat, 5), round(work_lng, 5)))

    if network is not None and (network.mrt_stations or network.krl_stations):
        mrt_plan = network.evaluate_rail_access("mrt", home_lat, home_lng, work_lat, work_lng)
        krl_plan = network.evaluate_rail_access("krl", home_lat, home_lng, work_lat, work_lng)
    else:
        mrt_plan = RailAccessPlan(
            reachable=False,
            origin_station="",
            dest_station="",
            access_walk_km=round(MRT_CATCHMENT_KM, 4),
            egress_walk_km=round(MRT_CATCHMENT_KM, 4),
            in_vehicle_km=dist_km,
        )
        krl_plan = RailAccessPlan(
            reachable=False,
            origin_station="",
            dest_station="",
            access_walk_km=round(KRL_CATCHMENT_KM, 4),
            egress_walk_km=round(KRL_CATCHMENT_KM, 4),
            in_vehicle_km=dist_km,
        )

    options = available_modes_for_persona(
        persona=persona,
        raw_dist_km=raw_km,
        mrt_reachable=mrt_plan.reachable,
        krl_reachable=krl_plan.reachable,
    )

    # Check parking_tariff multipliers affecting destination (work)
    parking_multiplier = 1.0
    dest_in_central = zones.contains_kelurahan_or_point(
        "central", work_lat, work_lng, str(work.get("kelurahan", ""))
    )
    for pol in policies:
        if pol.get("type") == "parking_tariff":
            pol_zone = str(pol.get("zone", "central"))
            if zones.contains_kelurahan_or_point(
                pol_zone, work_lat, work_lng, str(work.get("kelurahan", ""))
            ):
                parking_multiplier *= max(0.0, 1.0 + float(pol.get("change_ratio", 0.0)))

    # Check transit_fare multipliers
    transit_multiplier = 1.0
    for pol in policies:
        if pol.get("type") == "transit_fare":
            transit_multiplier *= max(0.0, 1.0 + float(pol.get("change_ratio", 0.0)))

    # Check flood events active at this tick along road path waypoints
    active_ev = get_active_events_at_tick(events, tick)
    route_flooded = False
    max_flood_depth_cm = 0
    for ev in active_ev:
        if ev.get("type") == "flood":
            area_id = str(ev.get("area_id", "jakarta_utara"))
            if (
                zones.path_intersects(area_id, waypoints)
                or zones.contains_kelurahan_or_point(
                    area_id, home_lat, home_lng, str(home.get("kelurahan", ""))
                )
                or zones.contains_kelurahan_or_point(
                    area_id, work_lat, work_lng, str(work.get("kelurahan", ""))
                )
            ):
                route_flooded = True
                max_flood_depth_cm = max(max_flood_depth_cm, int(ev.get("depth_cm", 30)))

    flood_delay_road_min = (
        int(round(max_flood_depth_cm * FLOOD_DELAY_ROAD_MIN_PER_CM)) if route_flooded else 0
    )
    flood_delay_brt_min = (
        int(round(max_flood_depth_cm * FLOOD_DELAY_BRT_MIN_PER_CM)) if route_flooded else 0
    )

    peak = is_peak_tick(tick)

    details: dict[str, dict[str, Any]] = {}
    for mode in options:
        cong_mult = PEAK_CONGESTION_MULTIPLIER.get(mode, 1.0) if peak else 1.0

        if mode == "walk":
            est_min = max(
                MIN_TRIP_MINUTES["walk"],
                int(round(dist_km * WALK_MINUTES_PER_KM)) + flood_delay_road_min,
            )
            cost_idr = 0
            flooded = route_flooded
        elif mode == "motorcycle":
            in_veh = dist_km * MOTORCYCLE_MINUTES_PER_KM * cong_mult
            est_min = max(
                MIN_TRIP_MINUTES["motorcycle"],
                int(round(in_veh + MOTORCYCLE_PARKING_EGRESS_MIN)) + flood_delay_road_min,
            )
            base_parking = (
                MOTORCYCLE_PARKING_CENTRAL_IDR
                if dest_in_central
                else MOTORCYCLE_PARKING_NON_CENTRAL_IDR
            )
            fuel_cost = int(round(dist_km * MOTORCYCLE_FUEL_IDR_PER_KM))
            cost_idr = int(round(fuel_cost + base_parking * parking_multiplier))
            flooded = route_flooded
        elif mode == "car":
            in_veh = dist_km * CAR_MINUTES_PER_KM * cong_mult
            est_min = max(
                MIN_TRIP_MINUTES["car"],
                int(round(in_veh + CAR_PARKING_EGRESS_MIN)) + flood_delay_road_min,
            )
            base_parking = (
                CAR_PARKING_CENTRAL_IDR if dest_in_central else CAR_PARKING_NON_CENTRAL_IDR
            )
            fuel_and_toll = int(round(dist_km * CAR_FUEL_AND_TOLL_IDR_PER_KM))
            cost_idr = int(round(fuel_and_toll + base_parking * parking_multiplier))
            flooded = route_flooded
        elif mode == "transjakarta":
            # Include short walk access/egress (~0.5 km total) + BRT wait + in-vehicle time
            access_egress_min = 0.5 * WALK_MINUTES_PER_KM
            in_veh = dist_km * TRANSJAKARTA_MINUTES_PER_KM * cong_mult
            est_min = max(
                MIN_TRIP_MINUTES["transjakarta"],
                int(round(access_egress_min + TRANSJAKARTA_WAIT_MIN + in_veh))
                + flood_delay_brt_min,
            )
            cost_idr = int(round(TRANSJAKARTA_BASE_FARE_IDR * transit_multiplier))
            flooded = route_flooded
        elif mode == "krl":
            access_min = krl_plan.access_walk_km * WALK_MINUTES_PER_KM
            egress_min = krl_plan.egress_walk_km * WALK_MINUTES_PER_KM
            rail_km = krl_plan.in_vehicle_km if krl_plan.reachable else dist_km
            in_veh = rail_km * KRL_IN_VEHICLE_MINUTES_PER_KM
            est_min = max(
                MIN_TRIP_MINUTES["krl"],
                int(round(access_min + KRL_WAIT_MIN + in_veh + egress_min)),
            )
            base_fare = KRL_BASE_FARE_IDR + KRL_INCREMENT_FARE_IDR * max(
                0, int((rail_km - KRL_DISTANCE_THRESHOLD_KM) // KRL_INCREMENT_STEP_KM)
            )
            cost_idr = int(round(base_fare * transit_multiplier))
            flooded = False
        elif mode == "mrt":
            access_min = mrt_plan.access_walk_km * WALK_MINUTES_PER_KM
            egress_min = mrt_plan.egress_walk_km * WALK_MINUTES_PER_KM
            rail_km = mrt_plan.in_vehicle_km if mrt_plan.reachable else dist_km
            in_veh = rail_km * MRT_IN_VEHICLE_MINUTES_PER_KM
            est_min = max(
                MIN_TRIP_MINUTES["mrt"],
                int(round(access_min + MRT_WAIT_MIN + in_veh + egress_min)),
            )
            base_fare = min(
                MRT_MAX_FARE_IDR,
                MRT_BASE_FARE_IDR
                + MRT_INCREMENT_FARE_IDR * int(rail_km // MRT_INCREMENT_STEP_KM),
            )
            cost_idr = int(round(base_fare * transit_multiplier))
            flooded = False
        elif mode == "ojol":
            in_veh = dist_km * OJOL_MINUTES_PER_KM * cong_mult
            est_min = max(
                MIN_TRIP_MINUTES["ojol"],
                int(round(in_veh + OJOL_WAIT_MIN)) + flood_delay_road_min,
            )
            cost_idr = max(
                OJOL_MIN_FARE_IDR,
                int(round(OJOL_BASE_FARE_IDR + dist_km * OJOL_IDR_PER_KM)),
            )
            flooded = route_flooded
        else:
            est_min = max(15, int(round(dist_km * 2.5 + 10)))
            cost_idr = 5000
            flooded = route_flooded

        details[mode] = {
            "est_minutes": int(est_min),
            "cost_idr": int(cost_idr),
            "flooded_on_route": bool(flooded),
        }

    return (
        options,
        details,
        format_active_policies(policies),
        format_active_events(active_ev),
    )
