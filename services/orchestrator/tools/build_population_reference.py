#!/usr/bin/env python3
"""Build app/data/population_reference.json from Satu Data Jakarta (Dukcapil DKI).

Dataset: "Data Jumlah Penduduk Berdasarkan Usia Per Kelurahan DKI Jakarta" — every kelurahan by
sex and 5-year age group, period 2013 (the most recent complete, openly published release found).
Only relative shares are used (which kelurahan are denser, which ages are more common); the totals
are Dukcapil registrations and are larger than BPS estimates.

Usage (from services/orchestrator): .venv/bin/python -I tools/build_population_reference.py
"""

import csv
import io
import json
import re
import urllib.request
from datetime import date
from pathlib import Path

SOURCE_URL = ("https://satudata.jakarta.go.id/backend/restapi/v1/datasets/export/15f39fbf390306e6318d58c3244796d8/"
              "data-jumlah-penduduk-berdasarkan-usia-per-kelurahan-dki-jakarta.csv")
DATA = Path(__file__).resolve().parent.parent / "app" / "data"
# Spelling differences between OpenStreetMap and Dukcapil.
ALIAS = {"TENGAH": "KAMPUNGTENGAH", "HALIMPERDANAKUSUMA": "HALIMPERDANAKUSUMAH",
         "HARAPANMULYA": "HARAPANMULIA", "KRENDANG": "KERENDANG"}
WORKING_AGE_BINS = ["15 s.d 19 tahun", "20 s.d 24 tahun", "25 s.d 29 tahun", "30 s.d 34 tahun",
                    "35 s.d 39 tahun", "40 s.d 44 tahun", "45 s.d 49 tahun", "50 s.d 54 tahun",
                    "55 s.d 59 tahun", "60 s.d 64 tahun"]


def norm(name: str) -> str:
    key = re.sub(r"[^A-Z0-9]", "", name.upper())
    return ALIAS.get(key, key)


def main() -> None:
    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "shadow-city-data-build/0.1"})
    with urllib.request.urlopen(request, timeout=180) as response:
        text = response.read().decode("utf-8-sig")
    rows = [{k.lstrip("﻿"): v for k, v in r.items()} for r in csv.DictReader(io.StringIO(text))]
    periods = {r["periode_data"] for r in rows}

    by_key: dict[str, dict] = {}
    for r in rows:
        if "SERIBU" in r["nama_kabupaten_kota"]:
            continue
        entry = by_key.setdefault(norm(r["nama_kelurahan"]), {"total": 0, "age_bins": {b: 0 for b in WORKING_AGE_BINS}})
        n = int(r["jumlah"])
        entry["total"] += n
        if r["usia"] in entry["age_bins"]:
            entry["age_bins"][r["usia"]] += n

    osm = json.loads((DATA / "kelurahan.json").read_text())["kelurahan"]
    out, missing = {}, []
    for k in osm:
        match = by_key.get(norm(k["kelurahan"]))
        if match:
            out[k["kelurahan"]] = match
        else:
            missing.append(k["kelurahan"])
    (DATA / "population_reference.json").write_text(json.dumps({
        "source": "Satu Data Jakarta / Dinas Dukcapil DKI Jakarta: Data Jumlah Penduduk Berdasarkan Usia Per Kelurahan",
        "url": SOURCE_URL,
        "period": sorted(periods),
        "retrieved": date.today().isoformat(),
        "note": "Relative shares only; totals are Dukcapil registrations. Kelurahan without a record get weight 0.",
        "age_bins": WORKING_AGE_BINS,
        "missing": missing,
        "kelurahan": out,
    }, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(out)} kelurahan matched, missing: {missing}, period {sorted(periods)}")


if __name__ == "__main__":
    main()
