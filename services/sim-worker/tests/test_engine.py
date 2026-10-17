"""Unit tests for sim-worker Layer 0 and Layer 1 engine, physics, and configuration.

Compatible with both `python -m unittest` (zero external dependencies) and `pytest`.
"""

from __future__ import annotations

import json
import os
import unittest
from typing import Any
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
    simulate_scenario_layer1,
    tick_to_local_time,
)
from sim_worker.physics import ZoneIndex, compute_options_detail, haversine_km


class FakeDecisionProvider:
    """Deterministic fake System One provider for unit tests."""

    def __init__(self, forced_mode: str | None = None) -> None:
        self.forced_mode = forced_mode
        self.last_items: list[dict[str, Any]] = []

    def decide_batch(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.last_items = items
        out: list[dict[str, Any]] = []
        for item in items:
            opts = item["options"]
            chosen = self.forced_mode if (self.forced_mode in opts) else opts[0]
            out.append(
                {
                    "request_id": item["request_id"],
                    "decision_id": f"d_{item['request_id']}",
                    "probabilities": {o: (1.0 if o == chosen else 0.0) for o in opts},
                    "chosen": chosen,
                    "reason_short": f"Chose {chosen} in test.",
                    "decided_by": "rule-fallback",
                    "model_version": "test-fake-v0",
                    "latency_ms": 1,
                }
            )
        return out


class TestSimWorkerLayer0And1(unittest.TestCase):
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

    def test_physics_options_detail_and_parking_policy(self) -> None:
        cfg = WorkerConfig.from_env()
        zones = ZoneIndex.from_file(cfg.zones_geojson_path)

        persona = {
            "persona_id": "p_s42_n50_00000",
            "cluster_id": "c_s42_n50_00000",
            "home": {"kelurahan": "Penjaringan", "lat": -6.1260, "lng": 106.7960},
            "work": {"kelurahan": "Gambir", "lat": -6.1750, "lng": 106.8230},
            "vehicles": ["car", "motorcycle"],
            "usual_mode": "car",
            "usual_departure_tick": 20,
            "cost_sensitivity": 0.5,
            "time_sensitivity": 0.7,
        }
        dist = haversine_km(
            persona["home"]["lat"],
            persona["home"]["lng"],
            persona["work"]["lat"],
            persona["work"]["lng"],
        )
        self.assertGreater(dist, 5.0)
        self.assertLess(dist, 10.0)

        opts_base, detail_base, pol_base, ev_base = compute_options_detail(
            persona=persona,
            tick=20,
            policies=[],
            events=[],
            zones=zones,
        )
        opts_pol, detail_pol, pol_str, ev_str = compute_options_detail(
            persona=persona,
            tick=20,
            policies=[{"type": "parking_tariff", "zone": "central", "change_ratio": 1.0}],
            events=[
                {
                    "type": "flood",
                    "area_id": "jakarta_utara",
                    "start_tick": 10,
                    "end_tick": 40,
                    "depth_cm": 40,
                }
            ],
            zones=zones,
        )

        self.assertEqual(opts_base, opts_pol)
        for opt in opts_pol:
            self.assertIn(opt, detail_pol)
        self.assertGreater(detail_pol["car"]["cost_idr"], detail_base["car"]["cost_idr"])
        self.assertTrue(detail_pol["car"]["flooded_on_route"])
        self.assertEqual(pol_str, ["parking_tariff:central:+100%"])
        self.assertEqual(ev_str, ["flood:jakarta_utara"])

    def test_simulate_scenario_layer1_end_to_end(self) -> None:
        cfg = WorkerConfig.from_env()
        zones = ZoneIndex.from_file(cfg.zones_geojson_path)
        scenario = {
            "scenario_id": "s_test_layer1",
            "seed": 42,
            "population_size": 2,
            "population_id": "pop_s42_n2",
            "policies": [{"type": "parking_tariff", "zone": "central", "change_ratio": 1.0}],
            "events": [],
        }
        personas = [
            {
                "persona_id": "p_00001",
                "cluster_id": "c_00001",
                "population_id": "pop_s42_n2",
                "home": {"kelurahan": "Pasar Minggu", "lat": -6.2871, "lng": 106.8439},
                "work": {"kelurahan": "Gambir", "lat": -6.1772, "lng": 106.8249},
                "income_band": "high",
                "vehicles": ["car"],
                "usual_mode": "car",
                "usual_departure_tick": 20,
                "cost_sensitivity": 0.2,
                "time_sensitivity": 0.8,
                "profile_summary": "Advisor commuting to Gambir.",
                "memory": [],
            },
            {
                "persona_id": "p_00002",
                "cluster_id": "c_00002",
                "population_id": "pop_s42_n2",
                "home": {"kelurahan": "Penjaringan", "lat": -6.1214, "lng": 106.7923},
                "work": {"kelurahan": "Setiabudi", "lat": -6.2088, "lng": 106.8302},
                "income_band": "middle",
                "vehicles": ["motorcycle"],
                "usual_mode": "motorcycle",
                "usual_departure_tick": 24,
                "cost_sensitivity": 0.7,
                "time_sensitivity": 0.6,
                "profile_summary": "Worker commuting to Setiabudi.",
                "memory": [],
            },
        ]

        fake_s1 = FakeDecisionProvider(forced_mode="transjakarta")
        result = simulate_scenario_layer1(
            scenario=scenario,
            personas=personas,
            zones=zones,
            decision_provider=fake_s1,
        )

        self.assertEqual(len(result.tick_states), TOTAL_TICKS)
        self.assertEqual(result.tick_states[0].status, ["at_home", "at_home"])
        self.assertEqual(result.tick_states[22].status[0], "traveling")
        self.assertEqual(result.tick_states[200].status, ["at_work", "at_work"])
        self.assertEqual(
            result.metrics_summary["citywide"]["mode_share"],
            {"transjakarta": 1.0},
        )
        self.assertEqual(len(result.metrics_summary["by_kelurahan"]), 2)


if __name__ == "__main__":
    unittest.main()
