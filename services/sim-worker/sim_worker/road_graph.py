"""Deterministic OpenStreetMap road network router and operational rail station index (Layer 2)."""

from __future__ import annotations

import bisect
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import networkx as nx

from sim_worker.assumptions import (
    FALLBACK_URBAN_DETOUR_FACTOR,
    KRL_CATCHMENT_KM,
    MRT_CATCHMENT_KM,
    RAIL_TRACK_DETOUR_FACTOR,
)

EARTH_RADIUS_KM = 6371.0


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


@dataclass(frozen=True)
class RailAccessPlan:
    """Station access, in-vehicle track distance, and egress plan for MRT or KRL."""

    reachable: bool
    origin_station: str
    dest_station: str
    access_walk_km: float
    egress_walk_km: float
    in_vehicle_km: float


@dataclass(frozen=True)
class RoutePlan:
    """Precomputed OSM road path between an origin and destination."""

    waypoints: tuple[tuple[float, float], ...]
    cumulative_km: tuple[float, ...]
    total_km: float

    def interpolate(self, fraction: float) -> tuple[float, float]:
        """Interpolate (lat, lng) at a given fraction [0.0, 1.0] along the road path."""
        if not self.waypoints:
            return (0.0, 0.0)
        if len(self.waypoints) == 1 or self.total_km <= 1e-6:
            return self.waypoints[0]

        clamped = max(0.0, min(1.0, fraction))
        target_km = clamped * self.total_km

        idx = bisect.bisect_right(self.cumulative_km, target_km) - 1
        idx = max(0, min(len(self.waypoints) - 2, idx))

        seg_start_km = self.cumulative_km[idx]
        seg_end_km = self.cumulative_km[idx + 1]
        seg_len = seg_end_km - seg_start_km

        lat1, lng1 = self.waypoints[idx]
        lat2, lng2 = self.waypoints[idx + 1]
        if seg_len <= 1e-9:
            return (lat2, lng2)

        seg_frac = (target_km - seg_start_km) / seg_len
        lat = lat1 + (lat2 - lat1) * seg_frac
        lng = lng1 + (lng2 - lng1) * seg_frac
        return (round(lat, 5), round(lng, 5))


class JakartaNetwork:
    """OSM road graph and operational MRT/KRL station index for DKI Jakarta."""

    def __init__(
        self,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        mrt_stations: list[dict[str, Any]],
        krl_stations: list[dict[str, Any]],
    ) -> None:
        self.nodes_by_id: dict[int, tuple[float, float]] = {}
        for n in sorted(nodes, key=lambda x: int(x["id"])):
            nid = int(n["id"])
            self.nodes_by_id[nid] = (float(n["lat"]), float(n["lng"]))

        self._sorted_node_ids: tuple[int, ...] = tuple(sorted(self.nodes_by_id.keys()))
        self.graph = nx.Graph()
        for nid in self._sorted_node_ids:
            lat, lng = self.nodes_by_id[nid]
            self.graph.add_node(nid, lat=lat, lng=lng)

        for e in sorted(edges, key=lambda x: (int(x["u"]), int(x["v"]))):
            u = int(e["u"])
            v = int(e["v"])
            dist_km = float(e["dist_km"])
            hw = str(e.get("highway", "tertiary"))
            self.graph.add_edge(u, v, dist_km=dist_km, highway=hw)

        self.mrt_stations: tuple[dict[str, Any], ...] = tuple(
            sorted(mrt_stations, key=lambda s: (str(s["name"]), int(s.get("osm_id", 0))))
        )
        self.krl_stations: tuple[dict[str, Any], ...] = tuple(
            sorted(krl_stations, key=lambda s: (str(s["name"]), int(s.get("osm_id", 0))))
        )

        self._is_connected: bool = (
            nx.is_connected(self.graph) if self.graph.number_of_nodes() > 0 else False
        )
        self._node_grid: dict[tuple[int, int], list[tuple[int, float, float]]] = {}
        for nid in self._sorted_node_ids:
            nlat, nlng = self.nodes_by_id[nid]
            cell = (int(math.floor(nlat * 100.0)), int(math.floor(nlng * 100.0)))
            self._node_grid.setdefault(cell, []).append((nid, nlat, nlng))

        self._snap_cache: dict[tuple[float, float], int] = {}
        self._node_path_cache: dict[tuple[int, int], list[int]] = {}
        self._route_cache: dict[tuple[float, float, float, float], RoutePlan] = {}
        self._rail_cache: dict[tuple[str, float, float, float, float], RailAccessPlan] = {}

    @classmethod
    def from_file(cls, path: Path | None = None) -> JakartaNetwork:
        if path is None:
            path = Path(__file__).resolve().parent / "data" / "jakarta_network.json"
        if not path.exists():
            return cls(nodes=[], edges=[], mrt_stations=[], krl_stations=[])
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            nodes=data.get("nodes") or [],
            edges=data.get("edges") or [],
            mrt_stations=data.get("mrt_stations") or [],
            krl_stations=data.get("krl_stations") or [],
        )

    def snap_node(self, lat: float, lng: float) -> int | None:
        """Snap (lat, lng) to nearest road graph node ID with deterministic tie-breaking."""
        if not self._sorted_node_ids:
            return None
        key = (round(float(lat), 5), round(float(lng), 5))
        cached = self._snap_cache.get(key)
        if cached is not None:
            return cached

        clat = int(math.floor(key[0] * 100.0))
        clng = int(math.floor(key[1] * 100.0))
        best_id = self._sorted_node_ids[0]
        best_dist = float("inf")

        for r in range(0, 6):
            for di in range(-r, r + 1):
                for dj in range(-r, r + 1):
                    if r > 0 and abs(di) != r and abs(dj) != r:
                        continue
                    for nid, nlat, nlng in self._node_grid.get((clat + di, clng + dj), ()):
                        d = round(haversine_km(key[0], key[1], nlat, nlng), 6)
                        if d < best_dist or (d == best_dist and nid < best_id):
                            best_dist = d
                            best_id = nid
            if best_dist < float("inf") and r >= 1 and best_dist <= (r * 0.85):
                self._snap_cache[key] = best_id
                return best_id

        for nid in self._sorted_node_ids:
            nlat, nlng = self.nodes_by_id[nid]
            dlat = abs(key[0] - nlat)
            dlng = abs(key[1] - nlng)
            if (dlat + dlng) * 111.0 > best_dist * 1.5:
                continue
            d = round(haversine_km(key[0], key[1], nlat, nlng), 6)
            if d < best_dist or (d == best_dist and nid < best_id):
                best_dist = d
                best_id = nid

        self._snap_cache[key] = best_id
        return best_id

    def route(self, lat1: float, lng1: float, lat2: float, lng2: float) -> RoutePlan:
        """Compute deterministic shortest road path between two points."""
        k1_lat, k1_lng = round(float(lat1), 5), round(float(lng1), 5)
        k2_lat, k2_lng = round(float(lat2), 5), round(float(lng2), 5)
        cache_key = (k1_lat, k1_lng, k2_lat, k2_lng)
        cached = self._route_cache.get(cache_key)
        if cached is not None:
            return cached

        u = self.snap_node(k1_lat, k1_lng)
        v = self.snap_node(k2_lat, k2_lng)

        waypoints: list[tuple[float, float]] = [(k1_lat, k1_lng)]
        has_road_path = (
            u is not None
            and v is not None
            and u != v
            and (self._is_connected or nx.has_path(self.graph, u, v))
        )
        if has_road_path and u is not None and v is not None:
            node_path = self._node_path_cache.get((u, v))
            if node_path is None:
                node_path = nx.shortest_path(self.graph, source=u, target=v, weight="dist_km")
                self._node_path_cache[(u, v)] = node_path
            for nid in node_path:
                pt = self.nodes_by_id[nid]
                if pt != waypoints[-1]:
                    waypoints.append(pt)
            if (k2_lat, k2_lng) != waypoints[-1]:
                waypoints.append((k2_lat, k2_lng))

            cum_km: list[float] = [0.0]
            total = 0.0
            for i in range(len(waypoints) - 1):
                p_a = waypoints[i]
                p_b = waypoints[i + 1]
                seg = haversine_km(p_a[0], p_a[1], p_b[0], p_b[1])
                total += seg
                cum_km.append(round(total, 5))

            plan = RoutePlan(
                waypoints=tuple(waypoints),
                cumulative_km=tuple(cum_km),
                total_km=max(0.8, round(total, 4)),
            )
        else:
            # Fallback if graph is empty or origin/destination snap to same node
            if (k2_lat, k2_lng) != waypoints[-1]:
                waypoints.append((k2_lat, k2_lng))
            raw_dist = haversine_km(k1_lat, k1_lng, k2_lat, k2_lng)
            est_road_km = max(0.8, round(raw_dist * FALLBACK_URBAN_DETOUR_FACTOR, 4))
            plan = RoutePlan(
                waypoints=tuple(waypoints),
                cumulative_km=(0.0, est_road_km) if len(waypoints) > 1 else (0.0,),
                total_km=est_road_km,
            )

        self._route_cache[cache_key] = plan
        return plan

    def _nearest_station(
        self, stations: tuple[dict[str, Any], ...], lat: float, lng: float
    ) -> tuple[dict[str, Any] | None, float]:
        if not stations:
            return (None, float("inf"))
        best_st: dict[str, Any] | None = None
        best_dist = float("inf")
        for st in stations:
            d = round(haversine_km(lat, lng, float(st["lat"]), float(st["lng"])), 4)
            if best_st is None or d < best_dist or (
                d == best_dist and str(st["name"]) < str(best_st["name"])
            ):
                best_st = st
                best_dist = d
        return (best_st, best_dist)

    def evaluate_rail_access(
        self,
        mode: str,
        home_lat: float,
        home_lng: float,
        work_lat: float,
        work_lng: float,
    ) -> RailAccessPlan:
        """Evaluate whether MRT or KRL is reachable from both home and work."""
        k1_lat, k1_lng = round(float(home_lat), 5), round(float(home_lng), 5)
        k2_lat, k2_lng = round(float(work_lat), 5), round(float(work_lng), 5)
        cache_key = (mode, k1_lat, k1_lng, k2_lat, k2_lng)
        cached = self._rail_cache.get(cache_key)
        if cached is not None:
            return cached

        if mode == "mrt":
            stations = self.mrt_stations
            catchment_km = MRT_CATCHMENT_KM
        elif mode == "krl":
            stations = self.krl_stations
            catchment_km = KRL_CATCHMENT_KM
        else:
            raise ValueError(f"Unsupported rail mode: {mode!r}")

        orig_st, orig_dist = self._nearest_station(stations, k1_lat, k1_lng)
        dest_st, dest_dist = self._nearest_station(stations, k2_lat, k2_lng)

        if (
            orig_st is None
            or dest_st is None
            or orig_dist > catchment_km
            or dest_dist > catchment_km
            or orig_st["name"] == dest_st["name"]
        ):
            plan = RailAccessPlan(
                reachable=False,
                origin_station=orig_st["name"] if orig_st else "",
                dest_station=dest_st["name"] if dest_st else "",
                access_walk_km=round(orig_dist, 4) if math.isfinite(orig_dist) else 0.0,
                egress_walk_km=round(dest_dist, 4) if math.isfinite(dest_dist) else 0.0,
                in_vehicle_km=0.0,
            )
        else:
            st_to_st_km = haversine_km(
                float(orig_st["lat"]),
                float(orig_st["lng"]),
                float(dest_st["lat"]),
                float(dest_st["lng"]),
            )
            in_veh_km = max(1.0, round(st_to_st_km * RAIL_TRACK_DETOUR_FACTOR, 4))
            plan = RailAccessPlan(
                reachable=True,
                origin_station=str(orig_st["name"]),
                dest_station=str(dest_st["name"]),
                access_walk_km=round(orig_dist, 4),
                egress_walk_km=round(dest_dist, 4),
                in_vehicle_km=in_veh_km,
            )

        self._rail_cache[cache_key] = plan
        return plan

