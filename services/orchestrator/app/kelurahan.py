"""Kelurahan used for population skeletons, from app/data/kelurahan.json.

The data file is built from OpenStreetMap by tools/build_kelurahan.py: all 262 mainland
kelurahan of DKI Jakarta with OSM centroids. Data © OpenStreetMap contributors, ODbL.

Homes are weighted by official population per kelurahan and ages follow each kelurahan's
official working-age structure: app/data/population_reference.json, built by
tools/build_population_reference.py from Satu Data Jakarta / Dukcapil DKI (period 2013, the most
recent complete open release; only relative shares are used).
TODO(data): workplaces use a short list of business districts as a placeholder for
employment data.
"""

import json
from pathlib import Path

_DATA = json.loads((Path(__file__).parent / "data" / "kelurahan.json").read_text())

# (kelurahan, kecamatan, lat, lng)
HOME_KELURAHAN = [(r["kelurahan"], r["kecamatan"], r["lat"], r["lng"]) for r in _DATA["kelurahan"]]

_REFERENCE = json.loads((Path(__file__).parent / "data" / "population_reference.json").read_text())
REFERENCE_SOURCE = f"{_REFERENCE['source']} (period {', '.join(_REFERENCE['period'])})"
AGE_BINS = _REFERENCE["age_bins"]  # "15 s.d 19 tahun" ... "60 s.d 64 tahun"

# Residents per kelurahan (official), aligned with HOME_KELURAHAN; 0 where Dukcapil has no record.
HOME_WEIGHTS = [(_REFERENCE["kelurahan"].get(k[0]) or {}).get("total", 0) for k in HOME_KELURAHAN]
# Working-age counts per 5-year bin for each kelurahan (official).
AGE_COUNTS = {name: entry["age_bins"] for name, entry in _REFERENCE["kelurahan"].items()}

WORK_DISTRICTS = [
    "Setiabudi", "Karet Kuningan", "Kuningan Timur", "Gambir",
    "Menteng", "Kebon Melati", "Gelora", "Kelapa Gading Barat",
]
WORK_KELURAHAN = [k for k in HOME_KELURAHAN if k[0] in WORK_DISTRICTS]
assert len(WORK_KELURAHAN) == len(WORK_DISTRICTS), "a work district is missing from the kelurahan data"
