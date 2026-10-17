#!/usr/bin/env python3
"""Build app/data/kelurahan.json from OpenStreetMap (Overpass API).

For every kelurahan (admin_level 7) in DKI Jakarta: name, kecamatan, centroid, and the
official population where OSM carries one (Dukcapil DKB 2023, source tagged in OSM).
Kepulauan Seribu is excluded: its residents do not commute by road.

Usage: python3 tools/build_kelurahan.py   (run from services/orchestrator)

Data © OpenStreetMap contributors, available under the Open Database License (ODbL).
"""

import json
import math
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

OVERPASS = "https://overpass-api.de/api/interpreter"
USER_AGENT = "shadow-city-data-build/0.1 (synthetic population research)"
OUTPUT = Path(__file__).resolve().parent.parent / "app" / "data" / "kelurahan.json"
AREA = 'area["boundary"="administrative"]["admin_level"="4"]["name"~"Jakarta"]->.dki;'
EXCLUDED_KECAMATAN = {"Kepulauan Seribu Utara", "Kepulauan Seribu Selatan"}


def overpass(query: str) -> list[dict]:
    body = urllib.parse.urlencode({"data": query}).encode()
    request = urllib.request.Request(OVERPASS, data=body, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.load(response)["elements"]


def outer_rings(relation: dict) -> list[list[tuple[float, float]]]:
    """Join a relation's outer member ways into closed (lng, lat) rings."""
    ways = [[(p["lon"], p["lat"]) for p in m["geometry"]]
            for m in relation["members"] if m["type"] == "way" and m.get("role") == "outer" and "geometry" in m]
    rings = []
    while ways:
        ring = ways.pop(0)
        joined = True
        while joined and ring[0] != ring[-1]:
            joined = False
            for i, way in enumerate(ways):
                if way[0] == ring[-1]:
                    ring += way[1:]
                elif way[-1] == ring[-1]:
                    ring += way[::-1][1:]
                elif way[-1] == ring[0]:
                    ring = way[:-1] + ring
                elif way[0] == ring[0]:
                    ring = way[::-1][:-1] + ring
                else:
                    continue
                ways.pop(i)
                joined = True
                break
        rings.append(ring)
    return rings


def contains(ring: list[tuple[float, float]], point: tuple[float, float]) -> bool:
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def nearest(kecamatan: list[tuple[str, list]], point: tuple[float, float]) -> str:
    """Fallback for centroids that fall just outside every polygon (coastal kelurahan)."""
    def distance(rings):
        return min(math.dist(point, vertex) for ring in rings for vertex in ring)
    return min(kecamatan, key=lambda k: distance(k[1]))[0]


def main() -> None:
    kecamatan = [(r["tags"]["name"], outer_rings(r)) for r in overpass(
        f'[out:json][timeout:180];{AREA}rel(area.dki)["boundary"="administrative"]["admin_level"="6"];out geom;')]
    kelurahan = overpass(
        f'[out:json][timeout:120];{AREA}rel(area.dki)["boundary"="administrative"]["admin_level"="7"];out center tags;')

    rows = []
    for element in kelurahan:
        tags, center = element["tags"], element["center"]
        point = (center["lon"], center["lat"])
        hits = [name for name, rings in kecamatan if any(contains(r, point) for r in rings)]
        kec = hits[0] if len(hits) == 1 else nearest(kecamatan, point)
        if kec in EXCLUDED_KECAMATAN or tags["name"].startswith("Pulau "):
            continue
        population = tags.get("population", "")
        rows.append({
            "kelurahan": tags["name"],
            "kecamatan": kec,
            "lat": round(center["lat"], 5),
            "lng": round(center["lon"], 5),
            "population": int(population) if population.isdigit() else None,
            "population_source": tags.get("source:population") if population.isdigit() else None,
            "population_year": tags.get("population:date") if population.isdigit() else None,
            "osm_relation": element["id"],
        })
    rows.sort(key=lambda r: (r["kecamatan"], r["kelurahan"]))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({
        "source": "OpenStreetMap via Overpass API; © OpenStreetMap contributors, ODbL",
        "built": date.today().isoformat(),
        "kelurahan": rows,
    }, indent=1, ensure_ascii=False) + "\n")
    known = sum(1 for r in rows if r["population"] is not None)
    print(f"{len(rows)} kelurahan in {len({r['kecamatan'] for r in rows})} kecamatan; "
          f"{known} with official population -> {OUTPUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
