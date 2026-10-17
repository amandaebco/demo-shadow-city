"""Deterministic physical calculations for Layer 1 (straight-line engine).

All physical numbers (distances, travel times, IDR costs, flood intersections)
are computed deterministically here. LLMs never compute physical numbers.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

EARTH_RADIUS_KM = 6371.0
URBAN_DETOUR_FACTOR = 1.25  # Straight-line to approximate urban travel distance


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Compute straight-line Haversine distance in kilometers between two WGS84 points."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)

    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_KM * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


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
        # Also check kecamatan match by polygon geometry
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


def format_active_policies(policies: list[dict[str, Any]]) -> list[str]:
    """Format active policies as strings like 'parking_tariff:central:+100%'."""
    out: list[str] = []
    for p in policies:
        ptype = p.get("type", "policy")
        zone = p.get("zone", "all")
        ratio = float(p.get("change_ratio", 0.0))
        pct = int(round(ratio * 100))
        out.append(f"{ptype}:{zone}:{pct:+d}%")
    return out


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
    """Format active events as strings like 'flood:jakarta_utara'."""
    return [f"{e.get('type', 'event')}:{e.get('area_id', 'unknown')}" for e in events]


def available_modes_for_persona(persona: dict[str, Any], dist_km: float) -> list[str]:
    """Determine which transport modes are available to this persona."""
    vehicles = set(persona.get("vehicles") or [])
    usual = persona.get("usual_mode", "motorcycle")

    options: list[str] = []
    if "motorcycle" in vehicles or usual == "motorcycle":
        options.append("motorcycle")
    if "car" in vehicles or usual == "car":
        options.append("car")

    for transit_mode in ("transjakarta", "krl", "mrt", "ojol"):
        options.append(transit_mode)

    if dist_km <= 4.0 or usual == "walk":
        options.append("walk")

    if usual not in options:
        options.insert(0, usual)

    return options


def compute_options_detail(
    persona: dict[str, Any],
    tick: int,
    policies: list[dict[str, Any]],
    events: list[dict[str, Any]],
    zones: ZoneIndex,
) -> tuple[list[str], dict[str, dict[str, Any]], list[str], list[str]]:
    """Compute options and options_detail for a persona at a given tick.

    Returns (options, options_detail, active_policies_str, active_events_str).
    """
    home = persona["home"]
    work = persona["work"]
    raw_km = haversine_km(home["lat"], home["lng"], work["lat"], work["lng"])
    dist_km = max(0.8, raw_km * URBAN_DETOUR_FACTOR)

    options = available_modes_for_persona(persona, raw_km)

    # Check parking_tariff multipliers affecting destination (work) or origin (home)
    parking_multiplier = 1.0
    dest_in_central = zones.contains_kelurahan_or_point(
        "central", work["lat"], work["lng"], work.get("kelurahan", "")
    )
    for pol in policies:
        if pol.get("type") == "parking_tariff":
            pol_zone = pol.get("zone", "central")
            if zones.contains_kelurahan_or_point(
                pol_zone, work["lat"], work["lng"], work.get("kelurahan", "")
            ):
                parking_multiplier *= max(0.0, 1.0 + float(pol.get("change_ratio", 0.0)))

    # Check transit_fare multipliers
    transit_multiplier = 1.0
    for pol in policies:
        if pol.get("type") == "transit_fare":
            transit_multiplier *= max(0.0, 1.0 + float(pol.get("change_ratio", 0.0)))

    # Check flood events active at this tick along straight-line route
    active_ev = get_active_events_at_tick(events, tick)
    route_flooded = False
    max_flood_depth_cm = 0
    for ev in active_ev:
        if ev.get("type") == "flood":
            area_id = ev.get("area_id", "jakarta_utara")
            if (
                zones.segment_intersects(
                    area_id, home["lat"], home["lng"], work["lat"], work["lng"]
                )
                or zones.contains_kelurahan_or_point(
                    area_id, home["lat"], home["lng"], home.get("kelurahan", "")
                )
                or zones.contains_kelurahan_or_point(
                    area_id, work["lat"], work["lng"], work.get("kelurahan", "")
                )
            ):
                route_flooded = True
                max_flood_depth_cm = max(max_flood_depth_cm, int(ev.get("depth_cm", 30)))

    flood_delay_road_min = int(round(max_flood_depth_cm * 0.55)) if route_flooded else 0
    flood_delay_brt_min = int(round(max_flood_depth_cm * 0.30)) if route_flooded else 0

    details: dict[str, dict[str, Any]] = {}
    for mode in options:
        if mode == "walk":
            est_min = max(5, int(round(dist_km * 12.5)) + flood_delay_road_min)
            cost_idr = 0
            flooded = route_flooded
        elif mode == "motorcycle":
            est_min = max(8, int(round(dist_km * 2.3 + 5)) + flood_delay_road_min)
            base_parking = 8000 if dest_in_central else 3000
            fuel_cost = int(round(dist_km * 650))
            cost_idr = int(round(fuel_cost + base_parking * parking_multiplier))
            flooded = route_flooded
        elif mode == "car":
            est_min = max(12, int(round(dist_km * 3.1 + 8)) + flood_delay_road_min)
            base_parking = 25000 if dest_in_central else 10000
            fuel_and_toll = int(round(dist_km * 2200))
            cost_idr = int(round(fuel_and_toll + base_parking * parking_multiplier))
            flooded = route_flooded
        elif mode == "transjakarta":
            est_min = max(15, int(round(dist_km * 2.6 + 12)) + flood_delay_brt_min)
            cost_idr = int(round(3500 * transit_multiplier))
            flooded = route_flooded
        elif mode == "krl":
            est_min = max(18, int(round(dist_km * 1.9 + 16)))
            base_fare = 3000 + 1000 * max(0, int((dist_km - 10.0) // 10.0))
            cost_idr = int(round(base_fare * transit_multiplier))
            flooded = False
        elif mode == "mrt":
            est_min = max(15, int(round(dist_km * 1.7 + 14)))
            base_fare = min(14000, 4000 + 1000 * int(dist_km // 3.0))
            cost_idr = int(round(base_fare * transit_multiplier))
            flooded = False
        elif mode == "ojol":
            est_min = max(10, int(round(dist_km * 2.4 + 6)) + flood_delay_road_min)
            cost_idr = max(12000, int(round(4000 + dist_km * 2800)))
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

