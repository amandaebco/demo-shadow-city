"""Build deterministic Jakarta OSM road network and operational rail station dataset.

Fetches from OpenStreetMap via the public Overpass API:
1. Operational MRT Jakarta stations (railway=station + station=subway, excluding
   construction/proposed and Phase 2 stations north of Bundaran HI).
2. Operational KRL Commuterline stations (railway=station + station=train in/around
   DKI Jakarta, excluding construction/proposed and intercity-only/HSR stations).
3. Major road network across mainland DKI Jakarta
   (highway in motorway, trunk, primary, secondary, tertiary and links),
   compacted to its largest connected component for deterministic NetworkX routing.

Output: services/sim-worker/sim_worker/data/jakarta_network.json
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import networkx as nx
import requests

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Mainland DKI Jakarta bounding box (south, west, north, east)
BBOX = (-6.38, 106.68, -6.09, 106.98)

# Bundaran HI latitude (~-6.1919). MRT Phase 2 stations north of Bundaran HI
# (Thamrin, Monas, Harmoni, Sawah Besar, Mangga Besar, Glodok, Kota) are under
# construction and must not be treated as operational.
MRT_BUNDARAN_HI_MAX_LAT = -6.1905

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_KM * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


def query_overpass(query: str) -> dict[str, Any]:
    last_err: Exception | None = None
    headers = {
        "User-Agent": "ShadowCitySimWorker/1.0 (GoogleCloudAIBuilderCup2026; contact: jay@ebconnect.com)",
        "Accept": "application/json",
    }
    for url in OVERPASS_URLS:
        try:
            print(f"Querying {url}...")
            resp = requests.post(
                url,
                data={"data": query.strip()},
                headers=headers,
                timeout=180,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            print(f"Warning: {url} failed: {exc}")
            last_err = exc
    raise RuntimeError(f"All Overpass endpoints failed: {last_err}")


def _is_under_construction_or_proposed(tags: dict[str, str]) -> bool:
    for key in (
        "construction",
        "proposed",
        "construction:railway",
        "proposed:railway",
        "disused:railway",
        "abandoned:railway",
    ):
        if key in tags:
            return True
    if tags.get("railway") in ("construction", "proposed", "disused", "abandoned"):
        return True
    if tags.get("operational_status") in ("closed", "under_construction", "proposed"):
        return True
    note_or_name = (
        f"{tags.get('name', '')} {tags.get('note', '')} {tags.get('description', '')}"
    ).lower()
    if "under construction" in note_or_name or "future" in note_or_name or "phase 2" in note_or_name:
        return True
    return False


def _clean_station_name(raw_name: str) -> str:
    name = re.sub(r"^Stasiun\s+(MRT\s+|KRL\s+)?", "", raw_name.strip(), flags=re.IGNORECASE)
    return name.strip()


def fetch_operational_stations() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    s, w, n, e = BBOX
    query = f"""
    [out:json][timeout:120];
    (
      node["railway"="station"]({s},{w},{n},{e});
      way["railway"="station"]({s},{w},{n},{e});
    );
    out center tags;
    """
    data = query_overpass(query)
    elements = data.get("elements", [])

    mrt_by_name: dict[str, dict[str, Any]] = {}
    krl_by_name: dict[str, dict[str, Any]] = {}

    for el in elements:
        tags = el.get("tags") or {}
        if _is_under_construction_or_proposed(tags):
            continue

        raw_name = tags.get("name") or tags.get("name:id") or tags.get("name:en")
        if not raw_name:
            continue

        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lng = el.get("lon") or (el.get("center") or {}).get("lon")
        if lat is None or lng is None:
            continue
        lat = round(float(lat), 5)
        lng = round(float(lng), 5)

        station_tag = (tags.get("station") or "").lower()
        network_tag = (tags.get("network") or "").lower()
        operator_tag = (tags.get("operator") or "").lower()
        clean_name = _clean_station_name(raw_name)
        key = clean_name.lower()

        # Exclude LRT, Monorail, Airport Rail Link-only, and High Speed Rail (Whoosh / KCIC)
        if (
            station_tag in ("light_rail", "monorail")
            or tags.get("light_rail") == "yes"
            or "lrt" in raw_name.lower()
            or "lrt" in network_tag
            or "lrt" in operator_tag
        ):
            continue
        if (
            "kcic" in operator_tag
            or "whoosh" in network_tag
            or "kereta cepat" in raw_name.lower()
            or "high speed" in network_tag
        ):
            continue

        # 1. Operational MRT stations: railway=station + station=subway
        if station_tag == "subway" or tags.get("subway") == "yes":
            # Exclude Phase 2 stations north of Bundaran HI unless explicitly marked open
            if lat > MRT_BUNDARAN_HI_MAX_LAT:
                continue
            record = {
                "osm_id": int(el["id"]),
                "name": clean_name,
                "lat": lat,
                "lng": lng,
                "station": "subway",
            }
            if key not in mrt_by_name or el["id"] < mrt_by_name[key]["osm_id"]:
                mrt_by_name[key] = record

        # 2. Operational KRL / heavy-rail stations: railway=station with station=train/commuter,
        # or standard OSM heavy-rail railway=station (where station tag is omitted or train/commuter)
        elif station_tag in ("train", "commuter", "") or tags.get("train") == "yes" or "commuter" in network_tag or "krl" in network_tag:
            excluded_non_krl = {
                "gambir",  # Intercity-only (KRL passes through without stopping)
                "cipinang",  # Freight/depot only
                "pasoso",  # Freight only
                "sungai lagoa",  # Freight only
                "jakarta gudang",  # Freight only
                "jakarta international stadium",  # Under construction / not yet operational KRL stop
                "jis",
                "halim",  # Whoosh HSR station
            }
            if clean_name.lower() in excluded_non_krl:
                continue
            record = {
                "osm_id": int(el["id"]),
                "name": clean_name,
                "lat": lat,
                "lng": lng,
                "station": "train",
            }
            if key not in krl_by_name or el["id"] < krl_by_name[key]["osm_id"]:
                krl_by_name[key] = record

    mrt_stations = sorted(mrt_by_name.values(), key=lambda x: (x["lat"], x["name"]))
    krl_stations = sorted(krl_by_name.values(), key=lambda x: (x["name"], x["osm_id"]))
    return mrt_stations, krl_stations


def fetch_and_build_road_graph() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    s, w, n, e = BBOX
    query = f"""
    [out:json][timeout:180];
    (
      way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary)$"]({s},{w},{n},{e});
    );
    out body;
    >;
    out skel qt;
    """
    data = query_overpass(query)
    elements = data.get("elements", [])

    raw_nodes: dict[int, tuple[float, float]] = {}
    ways: list[dict[str, Any]] = []

    for el in elements:
        etype = el.get("type")
        if etype == "node":
            raw_nodes[int(el["id"])] = (float(el["lat"]), float(el["lon"]))
        elif etype == "way":
            tags = el.get("tags") or {}
            if _is_under_construction_or_proposed(tags):
                continue
            ways.append(el)

    print(f"Fetched {len(raw_nodes)} raw nodes and {len(ways)} road ways from OSM.")

    # Quantize coordinates onto a ~180m grid (round to 3 decimal places ~110m, or 0.0015 deg ~165m)
    # to merge dual-carriageway parallel nodes and keep the road graph compact, fast, and connected
    # while preserving real OSM road geometry and topology.
    GRID_STEP = 0.002  # ~220 meters in Jakarta

    def quantize_id(lat: float, lng: float) -> tuple[int, int]:
        return (int(round(lat / GRID_STEP)), int(round(lng / GRID_STEP)))

    # Accumulate average real OSM coordinates per grid cell and build edges
    cell_coords: dict[tuple[int, int], list[tuple[float, float]]] = {}
    highway_rank = {
        "motorway": 5,
        "motorway_link": 4,
        "trunk": 4,
        "trunk_link": 3,
        "primary": 3,
        "primary_link": 2,
        "secondary": 2,
        "secondary_link": 1,
        "tertiary": 1,
    }

    raw_graph = nx.Graph()

    for way in ways:
        hw = (way.get("tags") or {}).get("highway", "tertiary")
        node_refs = way.get("nodes") or []
        prev_cell: tuple[int, int] | None = None
        for nid in node_refs:
            coords = raw_nodes.get(int(nid))
            if not coords:
                continue
            lat, lng = coords
            cell = quantize_id(lat, lng)
            cell_coords.setdefault(cell, []).append((lat, lng))
            if prev_cell is not None and cell != prev_cell:
                u, v = (prev_cell, cell) if prev_cell < cell else (cell, prev_cell)
                if raw_graph.has_edge(u, v):
                    old_hw = raw_graph[u][v]["highway"]
                    if highway_rank.get(hw, 1) > highway_rank.get(old_hw, 1):
                        raw_graph[u][v]["highway"] = hw
                else:
                    raw_graph.add_edge(u, v, highway=hw)
            prev_cell = cell

    # Compute representative coordinate for each cell
    cell_latlng: dict[tuple[int, int], tuple[float, float]] = {}
    for cell, pts in cell_coords.items():
        avg_lat = round(sum(p[0] for p in pts) / len(pts), 5)
        avg_lng = round(sum(p[1] for p in pts) / len(pts), 5)
        cell_latlng[cell] = (avg_lat, avg_lng)

    # Extract largest connected component
    if raw_graph.number_of_nodes() == 0:
        raise RuntimeError("Road graph has 0 nodes")

    largest_cc = max(nx.connected_components(raw_graph), key=len)
    sub = raw_graph.subgraph(largest_cc).copy()
    print(
        f"Largest connected component: {sub.number_of_nodes()} nodes, {sub.number_of_edges()} edges"
    )

    # Simplify degree-2 chains where adjacent edges are short (< 0.45 km combined)
    # so the graph stays compact while keeping waypoints at least every ~450m along roads.
    changed = True
    while changed:
        changed = False
        for node in sorted(list(sub.nodes())):
            if node not in sub or sub.degree(node) != 2:
                continue
            nbrs = sorted(list(sub.neighbors(node)))
            if len(nbrs) != 2:
                continue
            u, w_node = nbrs[0], nbrs[1]
            if sub.has_edge(u, w_node):
                continue
            lat_u, lng_u = cell_latlng[u]
            lat_n, lng_n = cell_latlng[node]
            lat_w, lng_w = cell_latlng[w_node]
            dist_unw = haversine_km(lat_u, lng_u, lat_n, lng_n) + haversine_km(
                lat_n, lng_n, lat_w, lng_w
            )
            if dist_unw <= 0.45:
                hw1 = sub[u][node]["highway"]
                hw2 = sub[node][w_node]["highway"]
                best_hw = hw1 if highway_rank.get(hw1, 1) >= highway_rank.get(hw2, 1) else hw2
                sub.remove_node(node)
                sub.add_edge(u, w_node, highway=best_hw)
                changed = True

    print(
        f"After chain simplification: {sub.number_of_nodes()} nodes, {sub.number_of_edges()} edges"
    )

    # Assign deterministic integer IDs 0..N-1 sorted by (lat, lng)
    sorted_cells = sorted(sub.nodes(), key=lambda c: (cell_latlng[c][0], cell_latlng[c][1], c))
    cell_to_id = {c: idx for idx, c in enumerate(sorted_cells)}

    nodes_out: list[dict[str, Any]] = []
    for c in sorted_cells:
        lat, lng = cell_latlng[c]
        nodes_out.append({"id": cell_to_id[c], "lat": lat, "lng": lng})

    edges_out: list[dict[str, Any]] = []
    for u, v, edata in sub.edges(data=True):
        uid = cell_to_id[u]
        vid = cell_to_id[v]
        if uid > vid:
            uid, vid = vid, uid
        lat1, lng1 = cell_latlng[sorted_cells[uid]]
        lat2, lng2 = cell_latlng[sorted_cells[vid]]
        dist_km = round(max(0.05, haversine_km(lat1, lng1, lat2, lng2)), 4)
        edges_out.append(
            {
                "u": uid,
                "v": vid,
                "dist_km": dist_km,
                "highway": edata["highway"],
            }
        )

    edges_out.sort(key=lambda e: (e["u"], e["v"]))
    return nodes_out, edges_out


def main() -> None:
    mrt_stations, krl_stations = fetch_operational_stations()
    print(f"Operational MRT stations ({len(mrt_stations)}):")
    for st in mrt_stations:
        print(f"  - {st['name']} ({st['lat']}, {st['lng']}) [osm_id={st['osm_id']}]")

    print(f"Operational KRL stations ({len(krl_stations)}):")
    for st in krl_stations:
        print(f"  - {st['name']} ({st['lat']}, {st['lng']}) [osm_id={st['osm_id']}]")

    out_path = (
        Path(__file__).resolve().parents[1]
        / "sim_worker"
        / "data"
        / "jakarta_network.json"
    )
    if out_path.exists():
        existing = json.loads(out_path.read_text(encoding="utf-8"))
        if existing.get("nodes") and existing.get("edges"):
            print(
                f"Reusing existing road graph ({len(existing['nodes'])} nodes, {len(existing['edges'])} edges)"
            )
            nodes = existing["nodes"]
            edges = existing["edges"]
        else:
            nodes, edges = fetch_and_build_road_graph()
    else:
        nodes, edges = fetch_and_build_road_graph()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": "OpenStreetMap via Overpass API; © OpenStreetMap contributors, ODbL",
        "bbox": list(BBOX),
        "mrt_stations": mrt_stations,
        "krl_stations": krl_stations,
        "nodes": nodes,
        "edges": edges,
    }
    out_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    size_kb = out_path.stat().st_size / 1024.0
    print(f"Wrote {out_path} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
