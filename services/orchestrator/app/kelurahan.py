"""Kelurahan used for population skeletons, from app/data/kelurahan.json.

The data file is built from OpenStreetMap by tools/build_kelurahan.py: all 262 mainland
kelurahan of DKI Jakarta with OSM centroids. Data © OpenStreetMap contributors, ODbL.

TODO(data): homes are drawn uniformly over kelurahan because official population is in
the data for only part of them (Dukcapil 2023 via OSM, missing for 22 kecamatan). Replace
with complete Dukcapil/BPS figures before treating the population as realistic.
TODO(data): workplaces use a short list of business districts as a placeholder for
employment data.
"""

import json
from pathlib import Path

_DATA = json.loads((Path(__file__).parent / "data" / "kelurahan.json").read_text())

# (kelurahan, kecamatan, lat, lng)
HOME_KELURAHAN = [(r["kelurahan"], r["kecamatan"], r["lat"], r["lng"]) for r in _DATA["kelurahan"]]

WORK_DISTRICTS = [
    "Setiabudi", "Karet Kuningan", "Kuningan Timur", "Gambir",
    "Menteng", "Kebon Melati", "Gelora", "Kelapa Gading Barat",
]
WORK_KELURAHAN = [k for k in HOME_KELURAHAN if k[0] in WORK_DISTRICTS]
assert len(WORK_KELURAHAN) == len(WORK_DISTRICTS), "a work district is missing from the kelurahan data"
