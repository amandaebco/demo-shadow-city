"""Unit tests for the Layer 0 sim-worker placeholder tick loop and configuration.

Compatible with both `python -m unittest` (zero external dependencies) and `pytest`.
"""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from sim_worker.config import (
    END_TICK,
    EXPECTED_FIRESTORE_DATABASE,
    EXPECTED_GCP_PROJECT_ID,
    START_TICK,
    TOTAL_TICKS,
    WorkerConfig,
)
from sim_worker.engine import (
    format_tick_id,
    make_tick_rng,
    run_placeholder_tick_loop,
    tick_to_local_time,
)


class TestSimWorkerLayer0(unittest.TestCase):
    def test_worker_config_defaults(self) -> None:
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("GCP_PROJECT_ID", "FIRESTORE_DATABASE")
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = WorkerConfig.from_env()
            self.assertEqual(cfg.gcp_project_id, EXPECTED_GCP_PROJECT_ID)
            self.assertEqual(cfg.firestore_database, EXPECTED_FIRESTORE_DATABASE)
            self.assertEqual(cfg.gcp_region, "asia-southeast2")

    def test_worker_config_rejects_wrong_project(self) -> None:
        with patch.dict(os.environ, {"GCP_PROJECT_ID": "wrong-project-id"}):
            with self.assertRaisesRegex(ValueError, "ebc-cloud-dev-03"):
                WorkerConfig.from_env()

    def test_worker_config_rejects_wrong_firestore_db(self) -> None:
        with patch.dict(os.environ, {"FIRESTORE_DATABASE": "(default)"}):
            with self.assertRaisesRegex(ValueError, "shadow-city"):
                WorkerConfig.from_env()

    def test_tick_formatting_and_simulated_time(self) -> None:
        self.assertEqual(format_tick_id(START_TICK), "0000")
        self.assertEqual(format_tick_id(84), "0084")
        self.assertEqual(format_tick_id(END_TICK), "0203")

        self.assertEqual(tick_to_local_time(0), "05:00")
        self.assertEqual(tick_to_local_time(12), "06:00")
        self.assertEqual(tick_to_local_time(203), "21:55")

    def test_placeholder_tick_loop_is_deterministic(self) -> None:
        states_a = run_placeholder_tick_loop(scenario_id="s_baseline_weekday", seed=42)
        states_b = run_placeholder_tick_loop(scenario_id="s_baseline_weekday", seed=42)

        self.assertEqual(len(states_a), TOTAL_TICKS)
        self.assertEqual(states_a, states_b)
        self.assertEqual(states_a[0].tick_id, "0000")
        self.assertEqual(states_a[-1].tick_id, "0203")
        self.assertEqual(
            states_a[84].to_firestore_dict(),
            {
                "scenario_id": "s_baseline_weekday",
                "tick": 84,
                "persona_ids": [],
                "lat": [],
                "lng": [],
                "mode": [],
                "status": [],
            },
        )

    def test_make_tick_rng_reproducibility(self) -> None:
        rng1 = make_tick_rng(seed=42, tick=84, salt="p_00421")
        rng2 = make_tick_rng(seed=42, tick=84, salt="p_00421")
        rng_diff = make_tick_rng(seed=43, tick=84, salt="p_00421")

        seq1 = [rng1.random() for _ in range(5)]
        seq2 = [rng2.random() for _ in range(5)]
        seq_diff = [rng_diff.random() for _ in range(5)]

        self.assertEqual(seq1, seq2)
        self.assertNotEqual(seq1, seq_diff)

    def test_zones_geojson_matches_contract(self) -> None:
        cfg = WorkerConfig.from_env()
        self.assertTrue(cfg.zones_geojson_path.exists(), f"Missing {cfg.zones_geojson_path}")
        fc = json.loads(cfg.zones_geojson_path.read_text(encoding="utf-8"))
        self.assertEqual(fc["type"], "FeatureCollection")
        by_id = {f["properties"]["zone_id"]: f for f in fc["features"]}
        self.assertEqual(set(by_id.keys()), {"central", "jakarta_utara"})

        central = by_id["central"]
        self.assertEqual(central["properties"]["type"], "parking_zone")
        self.assertEqual(
            central["properties"]["kecamatan"],
            ["Gambir", "Menteng", "Tanah Abang", "Setiabudi"],
        )
        self.assertIn(central["geometry"]["type"], ("Polygon", "MultiPolygon"))

        north = by_id["jakarta_utara"]
        self.assertEqual(north["properties"]["type"], "flood_area")
        self.assertEqual(
            north["properties"]["kecamatan"],
            ["Penjaringan", "Pademangan", "Tanjung Priok", "Koja", "Cilincing"],
        )
        self.assertIn(north["geometry"]["type"], ("Polygon", "MultiPolygon"))


if __name__ == "__main__":
    unittest.main()

